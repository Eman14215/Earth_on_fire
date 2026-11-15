"""EARTH ON FIRE: live-data FastAPI backend + bilingual web client.
No simulated observations, fake weather, AI responses, or payment flow.
"""
from __future__ import annotations
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import hashlib, hmac, math, os, re, secrets, sqlite3, threading, time
from typing import Annotated, Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA_DB = Path(os.getenv('FIRE_DB', str(ROOT / 'data' / 'fires.sqlite')))
USERS_DB = Path(os.getenv('USER_DB', str(ROOT / 'data' / 'users.sqlite')))
COOKIE_NAME = 'eof_session'
SESSION_DAYS = 7
REGION_NAMES = ('North Africa','West Africa','Central Africa','East Africa','Southern Africa')
VALID_INSTRUMENTS = ('VIIRS','MODIS')
VALID_CONF = ('High','Nominal')
VALID_DN = ('Day','Night')
AUTH_LIMIT: dict[str,list[float]] = {}
AUTH_LOCK = threading.Lock()


@contextmanager
def fire_conn():
    if not DATA_DB.is_file():
        raise HTTPException(503, 'Fire data has not been imported. Run python -m scripts.build_db.')
    c=sqlite3.connect(f'file:{DATA_DB}?mode=ro',uri=True,timeout=20)
    c.row_factory=sqlite3.Row
    try:
        yield c
    finally:
        c.close()


@contextmanager
def user_conn():
    c=sqlite3.connect(str(USERS_DB), timeout=10)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        with c:
            yield c
    finally:
        c.close()


def init_users():
    USERS_DB.parent.mkdir(parents=True,exist_ok=True)
    with user_conn() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS accounts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          full_name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('individual','company')),
          company_name TEXT,
          password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions(
          token_hash TEXT PRIMARY KEY,
          account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          expires TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS areas(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          name TEXT NOT NULL, country TEXT NOT NULL,
          lat REAL NOT NULL, lon REAL NOT NULL,
          radius_km REAL NOT NULL, category TEXT,
          created TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_area_owner ON areas(account_id);
        ''')

@asynccontextmanager
async def lifespan(app):
    init_users()
    if os.getenv('AUTO_SYNC', '1') == '1' and os.getenv('PYTEST_CURRENT_TEST') is None:
        def worker():
            while True:
                try:
                    from scripts.sync_github import sync_once
                    sync_once()
                except Exception as exc:
                    print('Background refresh unavailable; serving cached data:',repr(exc),flush=True)
                time.sleep(max(900,int(os.getenv('SYNC_INTERVAL_SECONDS','21600'))))
        threading.Thread(target=worker, daemon=True,name='fire-data-updater').start()
    yield

app=FastAPI(title='EARTH ON FIRE API',version='1.0.0',lifespan=lifespan,docs_url='/api/docs',redoc_url=None)
app.mount('/static',StaticFiles(directory=str(ROOT/'static')),name='static')

@app.get('/',include_in_schema=False)
def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/health')
def health():
    with fire_conn() as c:
        m=dict(c.execute('SELECT key,value FROM metadata').fetchall())
    return {'status':'ok','source':'NASA FIRMS via user-maintained GitHub repository', 'dataset':m,'auto_sync':os.getenv('AUTO_SYNC','1')=='1'}

@lru_cache(maxsize=1)
def geo_country_names():
    # Names in the current CSV import (only mapped African countries are exposed)
    with fire_conn() as c:
        entries=c.execute('SELECT DISTINCT region,country FROM observations WHERE country IS NOT NULL ORDER BY country').fetchall()
    regions={r:[] for r in REGION_NAMES}
    for reg,country in entries:
        if reg in regions: regions[reg].append(country)
    return regions

@app.get('/api/meta')
def meta():
    with fire_conn() as c:
        data=dict(c.execute('SELECT key,value FROM metadata').fetchall())
        counts=[dict(r) for r in c.execute('SELECT instrument,COUNT(*) AS count FROM observations WHERE country IS NOT NULL GROUP BY instrument')]
    return {'regions':geo_country_names(),'min_date':data.get('min_date'),'max_date':data.get('max_date'),'dataset':data,'instrument_counts':counts}

@app.get('/api/countries.geojson',include_in_schema=False)
def countries(): return FileResponse(ROOT/'data'/'africa_countries.geojson', media_type='application/geo+json')

class Filters(BaseModel):
    region: str | None = None
    country: str | None = None
    start: date | None = None
    end: date | None = None
    instrument: str | None = None
    confidence: str | None = None
    daynight: str | None = None

def filtered(
    region: str | None = Query(None), country: str | None = Query(None),
    start: date | None = Query(None), end: date | None = Query(None),
    instrument: str | None = Query(None), confidence: str | None = Query(None),
    daynight: str | None = Query(None)
) -> Filters:
    available=geo_country_names()
    if region and region not in REGION_NAMES: raise HTTPException(422,'Unknown region')
    if country and (country not in sum((v for v in available.values()),[])):
        raise HTTPException(422,'Unknown country')
    if region and country and country not in available[region]:
        raise HTTPException(422,'Country does not belong to selected region')
    if start and end and start>end:raise HTTPException(422,'Start date cannot be after end date')
    for value,choices,title in [(instrument,VALID_INSTRUMENTS,'instrument'),(confidence,VALID_CONF,'confidence'),(daynight,VALID_DN,'daynight')]:
        if value and value not in choices: raise HTTPException(422,'Unknown '+title)
    return Filters(region=region,country=country,start=start,end=end,instrument=instrument,confidence=confidence,daynight=daynight)

def where_clause(f: Filters, alias: str = ''):
    p=f'{alias}.' if alias else ''
    clauses=[f'{p}country IS NOT NULL']
    params=[]
    for key,value,col in [('region',f.region,'region'),('country',f.country,'country'),('start',f.start,'date'),('end',f.end,'date'),('instrument',f.instrument,'instrument'),('confidence',f.confidence,'confidence'),('daynight',f.daynight,'daynight')]:
        if value is not None:
            op='>=' if key=='start' else '<=' if key=='end' else '='
            clauses.append(f'{p}{col} {op} ?')
            params.append(str(value))
    return ' WHERE '+' AND '.join(clauses),params

@app.get('/api/dashboard')
def dashboard(f: Annotated[Filters,Depends(filtered)]):
    w,p=where_clause(f)
    with fire_conn() as c:
        summary=dict(c.execute('SELECT COUNT(*) as detections,COALESCE(MAX(frp),0) AS max_frp, COUNT(DISTINCT date) AS days,COUNT(DISTINCT country) AS countries, SUM(CASE WHEN confidence="High" THEN 1 ELSE 0 END) AS high_confidence FROM observations'+w,p).fetchone())
        daily=[dict(r) for r in c.execute('SELECT date,COUNT(*) AS count,COUNT(DISTINCT country) AS countries,MAX(frp) AS max_frp FROM observations'+w+' GROUP BY date ORDER BY date',p)]
        sensors=[dict(r) for r in c.execute('SELECT instrument,COUNT(*) AS count,ROUND(AVG(frp),2) AS mean_frp,ROUND(MAX(frp),2) AS max_frp FROM observations'+w+' GROUP BY instrument ORDER BY count DESC',p)]
        daynight=[dict(r) for r in c.execute('SELECT daynight,COUNT(*) AS count FROM observations'+w+' GROUP BY daynight',p)]
        confidence=[dict(r) for r in c.execute('SELECT confidence,COUNT(*) AS count FROM observations'+w+' GROUP BY confidence',p)]
        byregion=[dict(r) for r in c.execute('SELECT region,COUNT(*) AS count FROM observations'+w+' GROUP BY region ORDER BY count DESC',p)]
        bycountry=[dict(r) for r in c.execute('SELECT country,COUNT(*) AS count FROM observations'+w+' GROUP BY country ORDER BY count DESC LIMIT 12',p)]
        hours=[dict(r) for r in c.execute('SELECT SUBSTR(time,1,2) AS hour,COUNT(*) AS count FROM observations'+w+' AND time IS NOT NULL GROUP BY SUBSTR(time,1,2) ORDER BY hour',p)]
        severity=[dict(r) for r in c.execute('SELECT severity,COUNT(*) AS count FROM observations'+w+' GROUP BY severity ORDER BY count DESC',p)]
        recent=[dict(r) for r in c.execute('SELECT date,time,lat,lon,country,instrument,satellite,confidence,daynight,ROUND(frp,2) as frp FROM observations'+w+' ORDER BY date DESC,time DESC LIMIT 15',p)]
        top=[dict(r) for r in c.execute('SELECT date,time,lat,lon,country,instrument,confidence,ROUND(frp,2) AS frp FROM observations'+w+' ORDER BY frp DESC LIMIT 10',p)]
    summary['high_confidence']=summary['high_confidence'] or 0
    return {'summary':summary,'daily':daily,'sensors':sensors,'daynight':daynight,'confidence':confidence,'regions':byregion,'countries':bycountry,'hours':hours,'frp_bands':severity,'recent':recent,'top':top}

@app.get('/api/hotspots')
def hotspots(f: Annotated[Filters,Depends(filtered)], limit:int=Query(1800,ge=100,le=4000)):
    # Group observed detections into actual 0.25-degree observation-density cells.
    # Heat intensity indicates detection density; it is NOT a fire probability map.
    w,p=where_clause(f)
    with fire_conn() as c:
        cells=[dict(row) for row in c.execute('''SELECT tile_lat,tile_lon,SUM(n) AS count,MAX(max_frp) AS max_frp FROM tiles'''+w+''' GROUP BY tile_lat,tile_lon ORDER BY count DESC LIMIT ?''',p+[limit]).fetchall()]
        total=int(c.execute('SELECT COUNT(DISTINCT (tile_lat*10000+tile_lon)) FROM tiles'+w,p).fetchone()[0])
    for x in cells:
        x['lat']=round((x.pop('tile_lat')+.5)/4-90,4)
        x['lon']=round((x.pop('tile_lon')+.5)/4-180,4)
    return {'cells':cells,'returned':len(cells),'total_cells':total,'resolution_degrees':0.25,'sorted_by':'detection_count','truncated':len(cells)<total}

@app.get('/api/observations.csv')
def export_csv(f: Annotated[Filters,Depends(filtered)]):
    # Export daily aggregate (not 400k raw rows) as a user-friendly CSV.
    from fastapi.responses import StreamingResponse
    w,p=where_clause(f)
    def stream():
        import csv,io
        out=io.StringIO();wr=csv.writer(out);wr.writerow(['date','country','instrument','detections','max_frp_mw']);yield out.getvalue()
        with fire_conn() as c:
            for row in c.execute('SELECT date,country,instrument,COUNT(*),ROUND(MAX(frp),2) FROM observations'+w+' GROUP BY date,country,instrument ORDER BY date DESC,country',p):
                out=io.StringIO();csv.writer(out).writerow(row);yield out.getvalue()
    return StreamingResponse(stream(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="earth_on_fire_summary.csv"'})

# Auth: salted PBKDF2, random opaque database-backed sessions, HttpOnly SameSite cookies.
class Register(BaseModel):
    email:str=Field(min_length=5,max_length=250)
    password:str=Field(min_length=10,max_length=200)
    full_name:str=Field(min_length=2,max_length=100)
    role:Literal['individual','company']='individual'
    company_name:str|None=Field(None,max_length=160)

class Login(BaseModel):
    email:str
    password:str

def now():return datetime.now(timezone.utc)
def digest(token:str):return hashlib.sha256(token.encode()).hexdigest()
def password_hash(password,salt):return hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),310000).hex()
def account_public(a):return {'id':a['id'],'email':a['email'],'full_name':a['full_name'],'role':a['role'],'company_name':a['company_name']}
def set_session(c,uid,response):
    token=secrets.token_urlsafe(48)
    until=now()+timedelta(days=SESSION_DAYS)
    c.execute('DELETE FROM sessions WHERE expires < ?',(now().isoformat(),))
    c.execute('INSERT INTO sessions VALUES (?,?,?)',(digest(token),uid,until.isoformat()))
    response.set_cookie(COOKIE_NAME,token,max_age=SESSION_DAYS*86400,httponly=True,samesite='lax',secure=os.getenv('COOKIE_SECURE','0')=='1',path='/')

def rate_limit(request:Request,identity:str):
    ip=(request.client.host if request.client else 'unknown')
    key=ip+':'+identity.lower()
    current=time.monotonic()
    with AUTH_LOCK:
        q=[v for v in AUTH_LIMIT.get(key,[]) if current-v<600]
        if len(q)>=8:raise HTTPException(429,'Too many attempts. Try again later.')
        q.append(current);AUTH_LIMIT[key]=q
        if len(AUTH_LIMIT)>10000: AUTH_LIMIT.clear()

@app.post('/api/auth/register',status_code=201)
def register(payload:Register,response:Response,request:Request):
    email=payload.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise HTTPException(422,'Invalid email address')
    if payload.role=='company' and not (payload.company_name or '').strip():raise HTTPException(422,'Company name is required')
    rate_limit(request,'register')
    salt=secrets.token_hex(16)
    with user_conn() as c:
        try:
            cur=c.execute('INSERT INTO accounts(email,full_name,role,company_name,password_salt,password_hash,created) VALUES(?,?,?,?,?,?,?)',
                (email,payload.full_name.strip(),payload.role,(payload.company_name or '').strip() or None,salt,password_hash(payload.password,salt),now().isoformat()))
        except sqlite3.IntegrityError:raise HTTPException(409,'Email already registered')
        set_session(c,cur.lastrowid,response)
        result=c.execute('SELECT * FROM accounts WHERE id=?',(cur.lastrowid,)).fetchone()
    return {'account':account_public(result)}

@app.post('/api/auth/login')
def login(payload:Login,response:Response,request:Request):
    rate_limit(request,payload.email)
    with user_conn() as c:
        row=c.execute('SELECT * FROM accounts WHERE email=?',(payload.email.strip().lower(),)).fetchone()
        if not row:
            # Keep missing-email timing comparable to an incorrect password
            password_hash(payload.password,'00'*16)
            raise HTTPException(401,'Incorrect email or password')
        if not hmac.compare_digest(row['password_hash'],password_hash(payload.password,row['password_salt'])):
            raise HTTPException(401,'Incorrect email or password')
        set_session(c,row['id'],response)
    return {'account':account_public(row)}

def current_account(token: str|None=Cookie(default=None,alias=COOKIE_NAME)):
    if not token:raise HTTPException(401,'Sign in to use saved areas')
    with user_conn() as c:
        row=c.execute('''SELECT a.* FROM sessions s JOIN accounts a ON s.account_id=a.id WHERE s.token_hash=? AND s.expires>?''',(digest(token),now().isoformat())).fetchone()
    if not row:raise HTTPException(401,'Session expired. Sign in again.')
    return account_public(row)

@app.get('/api/auth/me')
def me(account=Depends(current_account)):return {'account':account}

@app.post('/api/auth/logout')
def logout(response:Response,token: str|None=Cookie(default=None,alias=COOKIE_NAME)):
    if token:
        with user_conn() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(digest(token),))
    response.delete_cookie(COOKIE_NAME,path='/')
    return {'ok':True}

class AreaCreate(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    country:str
    lat:float=Field(ge=-35,le=38)
    lon:float=Field(ge=-20,le=55)
    radius_km:float=Field(default=50,ge=1,le=500)
    category:str|None=Field(default=None,max_length=100)


def haversine(lat1,lon1,lat2,lon2):
    a,b,c,d=map(math.radians,(lat1,lon1,lat2,lon2))
    q=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371.0088*2*math.asin(min(1,math.sqrt(q)))

@app.get('/api/areas')
def list_areas(account=Depends(current_account)):
    with user_conn() as uc:
        rows=[dict(a) for a in uc.execute('SELECT id,name,country,lat,lon,radius_km,category,created FROM areas WHERE account_id=? ORDER BY id DESC',(account['id'],))]
    with fire_conn() as fc:
        for a in rows:
            # Indexed country filter + bounding rectangle, exact Haversine test.
            delta_lat=a['radius_km']/110.574
            delta_lon=min(180,a['radius_km']/(111.32*max(.05,math.cos(math.radians(a['lat'])))))
            candidates=fc.execute('''SELECT lat,lon,frp,date FROM observations WHERE country=? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?''',
              (a['country'],a['lat']-delta_lat,a['lat']+delta_lat,a['lon']-delta_lon,a['lon']+delta_lon))
            count=0; max_frp=0;last=None
            for r in candidates:
                if haversine(a['lat'],a['lon'],r['lat'],r['lon'])<=a['radius_km']:
                    count+=1;max_frp=max(max_frp,r['frp'] or 0)
                    if last is None or r['date']>last:last=r['date']
            a['detections']=count;a['max_frp']=round(max_frp,2);a['latest_detection']=last
    return {'areas':rows}

@app.post('/api/areas',status_code=201)
def add_area(payload:AreaCreate,account=Depends(current_account)):
    with fire_conn() as c:
        row=c.execute('SELECT region FROM observations WHERE country=? LIMIT 1',(payload.country,)).fetchone()
    if row is None:raise HTTPException(422,'Choose a listed African country')
    # Prevent storing a monitored point in a different country.
    import json
    from shapely.geometry import Point,shape
    geo=__import__('json').loads((ROOT/'data'/'africa_countries.geojson').read_text(encoding='utf-8'))
    polygon=next((shape(feature['geometry']) for feature in geo['features'] if feature['properties']['name']==payload.country),None)
    if polygon is None or not polygon.covers(Point(payload.lon,payload.lat)):
        raise HTTPException(422,'Coordinates do not fall inside the selected country (low-resolution boundaries).')
    with user_conn() as c:
        n=c.execute('SELECT COUNT(*) FROM areas WHERE account_id=?',(account['id'],)).fetchone()[0]
        if n>=30:raise HTTPException(400,'Maximum 30 saved areas per account')
        cur=c.execute('INSERT INTO areas(account_id,name,country,lat,lon,radius_km,category,created) VALUES(?,?,?,?,?,?,?,?)',
          (account['id'],payload.name.strip(),payload.country,payload.lat,payload.lon,payload.radius_km,payload.category,now().isoformat()))
    return {'id':cur.lastrowid,'ok':True}

@app.delete('/api/areas/{area_id}')
def remove_area(area_id:int,account=Depends(current_account)):
    with user_conn() as c:
        result=c.execute('DELETE FROM areas WHERE account_id=? AND id=?',(account['id'],area_id))
        if not result.rowcount:raise HTTPException(404,'Area not found')
    return {'ok':True}
