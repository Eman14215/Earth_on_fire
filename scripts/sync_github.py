"""Atomic fire-data refresh from team's existing GitHub Actions CSV.
Run manually: python -m scripts.sync_github . Also runs from app startup every 6h.
"""
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import json,os,csv,shutil,tempfile
from .build_db import build,ROOT

REPO='Eman14215/africa_fires_data'
API=f'https://api.github.com/repos/{REPO}/commits?path=africa_fires_cleaned.csv&per_page=1'
RAW=f'https://raw.githubusercontent.com/{REPO}/main/africa_fires_cleaned.csv'
DB=Path(os.getenv('FIRE_DB',str(ROOT/'data'/'fires.sqlite')))
CSV=ROOT/'data'/'africa_fires_cleaned.csv'

def fetch(url,timeout=25):
    return urlopen(Request(url,headers={'User-Agent':'earth-on-fire-dashboard/1.0','Accept':'application/vnd.github+json'}),timeout=timeout)

def get_metadata(db):
    import sqlite3
    if not db.exists():return {}
    with sqlite3.connect(str(db)) as c:
        return dict(c.execute('SELECT key,value FROM metadata').fetchall())

def sync_once():
    import sqlite3
    with fetch(API,timeout=12) as stream:
        commits=json.load(stream)
    if not commits or not commits[0].get('sha'):raise ValueError('No upstream revision received')
    sha=commits[0]['sha']
    current=get_metadata(DB)
    if sha==current.get('source_commit'):
        return {'updated':False,'commit':sha}
    stage=Path(tempfile.mkdtemp(prefix='.eof_sync_',dir=str(ROOT/'data')))
    try:
        candidate=stage/'africa_fires_cleaned.csv'
        with fetch(RAW,timeout=40) as src, candidate.open('wb') as dest:
            shutil.copyfileobj(src,dest,1024*1024)
        if candidate.stat().st_size<10000:raise ValueError('Suspiciously small CSV')
        with candidate.open('r',encoding='utf-8-sig',newline='') as f:
            reader=csv.reader(f);head=next(reader)
            if not {'latitude','longitude','acq_date','frp','Africa_Region','Confidence_Level'}.issubset(head):
                raise ValueError('Unexpected CSV schema from GitHub')
        target=stage/'fires.sqlite'
        build(candidate,target,commit_sha=sha)
        # Atomic swap: existing API requests finish with old DB, new requests see the new DB.
        os.replace(target,DB)
        shutil.copyfile(candidate,CSV)
        # Geo metadata list cache must refresh when new countries appear.
        try:
            from app import geo_country_names
            geo_country_names.cache_clear()
        except ImportError:pass
        return {'updated':True,'commit':sha}
    finally:
        shutil.rmtree(stage,ignore_errors=True)

if __name__=='__main__':
    print(sync_once())
