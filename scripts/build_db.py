"""Import user-provided cleaned NASA FIRMS CSV without modifying or re-cleaning it.
Derived geometry (country/UN M49 subregion) is stored separately in SQLite.
Usage: python -m scripts.build_db --csv data/africa_fires_cleaned.csv --db data/fires.sqlite
"""
from __future__ import annotations
import argparse, json, sqlite3, time
from pathlib import Path
import numpy as np
import pandas as pd
from shapely import STRtree, points
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / 'data' / 'africa_countries.geojson'
REGIONS = {
    'North Africa': {'Algeria', 'Egypt', 'Libya', 'Morocco', 'Sudan', 'Tunisia', 'W. Sahara'},
    'West Africa': {'Benin', 'Burkina Faso', 'Gambia', 'Ghana', 'Guinea', 'Guinea-Bissau', "Côte d'Ivoire", 'Liberia', 'Mali', 'Mauritania', 'Niger', 'Nigeria', 'Senegal', 'Sierra Leone', 'Togo'},
    'Central Africa': {'Angola', 'Cameroon', 'Central African Rep.', 'Chad', 'Congo', 'Dem. Rep. Congo', 'Eq. Guinea', 'Gabon'},
    'East Africa': {'Burundi', 'Djibouti', 'Eritrea', 'Ethiopia', 'Kenya', 'Madagascar', 'Malawi', 'Mozambique', 'Rwanda', 'Somalia', 'Somaliland', 'S. Sudan', 'Tanzania', 'Uganda', 'Zambia', 'Zimbabwe'},
    'Southern Africa': {'Botswana', 'Lesotho', 'Namibia', 'South Africa', 'eSwatini'},
}
NAME_TO_REGION = {name: region for region, names in REGIONS.items() for name in names}

def build(csv_path: Path, db_path: Path, commit_sha: str = ''):
    csv_path = Path(csv_path)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    if db_path.exists(): db_path.unlink()
    geo = json.loads(GEO.read_text(encoding='utf-8'))
    polys = [shape(feature['geometry']) for feature in geo['features']]
    countries = [feature['properties']['name'] for feature in geo['features']]
    missing = sorted(set(countries) - set(NAME_TO_REGION))
    if missing: raise ValueError(f'Country region mapping missing: {missing}')
    tree = STRtree(polys)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript('''
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=OFF;
        PRAGMA cache_size=-160000;
        CREATE TABLE observations (
          id INTEGER PRIMARY KEY,
          date TEXT NOT NULL, time TEXT,
          lat REAL NOT NULL, lon REAL NOT NULL,
          country TEXT, region TEXT,
          source_region TEXT,
          instrument TEXT, satellite TEXT,
          confidence TEXT, daynight TEXT,
          frp REAL, brightness REAL, temp_c REAL, anomaly REAL,
          severity TEXT,
          tile_lat INTEGER, tile_lon INTEGER
        );
        CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT);
        ''')
        sql = '''INSERT INTO observations(date,time,lat,lon,country,region,source_region,instrument,satellite,confidence,daynight,frp,brightness,temp_c,anomaly,severity,tile_lat,tile_lon)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''
        size=0; africa_count=0
        required={'latitude','longitude','acq_date','frp','instrument','Confidence_Level','daynight','Africa_Region'}
        for chunk in pd.read_csv(csv_path, chunksize=35000, dtype={'acq_time':'string','Fire_Time':'string'}, low_memory=False):
            if not required.issubset(chunk.columns):
                raise ValueError('Missing source columns: '+','.join(sorted(required-set(chunk.columns))))
            lat=chunk['latitude'].to_numpy(dtype=float);lon=chunk['longitude'].to_numpy(dtype=float)
            xy=points(lon,lat)
            pair=tree.query(xy,predicate='intersects')
            labels=np.full(len(chunk),None,dtype=object)
            if pair.shape[1]: labels[pair[0]] = np.array(countries,dtype=object)[pair[1]]
            region=[NAME_TO_REGION.get(c) for c in labels]
            frame=pd.DataFrame({
                'date':chunk['acq_date'],
                'time':chunk['Fire_Time'].fillna(''),
                'lat':lat,'lon':lon,
                'country':labels,'region':region,
                'source_region':chunk['Africa_Region'],
                'instrument':chunk['instrument'],
                'satellite':chunk['satellite'],
                'confidence':chunk['Confidence_Level'],
                'daynight':chunk['daynight'],
                'frp':pd.to_numeric(chunk['frp'],errors='coerce'),
                'brightness':pd.to_numeric(chunk['brightness'],errors='coerce'),
                'temp_c':pd.to_numeric(chunk['Temp_Celsius'],errors='coerce') if 'Temp_Celsius' in chunk else None,
                'anomaly':pd.to_numeric(chunk['Thermal_Anomaly'],errors='coerce') if 'Thermal_Anomaly' in chunk else None,
                'severity':chunk['Fire_Severity'] if 'Fire_Severity' in chunk else None,
                'tile_lat':np.floor((lat+90)*4).astype(int),
                'tile_lon':np.floor((lon+180)*4).astype(int),
            })
            frame=frame.astype(object).where(pd.notna(frame),None)
            conn.executemany(sql,frame.itertuples(index=False,name=None))
            size+=len(chunk)
            africa_count+=int(np.count_nonzero(pd.notnull(labels)))
            print(f'Imported {size:,} records; in African country polygons {africa_count:,}',flush=True)
        if size==0: raise ValueError('Empty CSV is not valid')
        conn.commit()
        print('Creating indexes + map aggregation...', flush=True)
        conn.executescript('''
        CREATE INDEX ix_ob_geo ON observations(country,date);
        CREATE INDEX ix_ob_region_date ON observations(region,date);
        CREATE INDEX ix_ob_date_inst ON observations(date,instrument);
        CREATE INDEX ix_ob_time ON observations(date DESC,time DESC);
        CREATE TABLE tiles AS
          SELECT date,country,region,instrument,confidence,daynight,tile_lat,tile_lon,
                 COUNT(*) AS n,MAX(frp) AS max_frp,MAX(brightness) AS max_brightness
          FROM observations WHERE country IS NOT NULL
          GROUP BY date,country,region,instrument,confidence,daynight,tile_lat,tile_lon;
        CREATE INDEX ix_tiles_scope ON tiles(region,country,date,instrument,confidence,daynight);
        CREATE INDEX ix_tiles_date ON tiles(date);
        ''')
        dmin,dmax=conn.execute('SELECT MIN(date), MAX(date) FROM observations WHERE country IS NOT NULL').fetchone()
        entries={
          'imported_rows':size, 'africa_rows':africa_count, 'outside_africa_rows':size-africa_count,
          'min_date':dmin, 'max_date':dmax,
          'source_csv':csv_path.name, 'source_commit':commit_sha,
          'imported_at_utc':pd.Timestamp.now(tz='UTC').isoformat(),
          'country_polygons':'Natural Earth lowres (public domain); approximation, small islands may be absent',
        }
        conn.executemany('INSERT INTO metadata VALUES (?,?)',[(k,str(v)) for k,v in entries.items()]);conn.commit()
        print('Finished:',entries,'db_size_MB',round(db_path.stat().st_size/1e6,1), flush=True)
    except BaseException:
        conn.close()
        db_path.unlink(missing_ok=True)
        raise
    finally:
        try: conn.close()
        except:pass

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--csv',default=str(ROOT/'data/africa_fires_cleaned.csv'));p.add_argument('--db',default=str(ROOT/'data/fires.sqlite'));p.add_argument('--commit',default='')
    a=p.parse_args();build(Path(a.csv),Path(a.db),a.commit)
