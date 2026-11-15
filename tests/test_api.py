"""Smoke + integration tests against the shipped 10-day NASA FIRMS sample snapshot."""
import os
os.environ['AUTO_SYNC']='0'
import pytest
from fastapi.testclient import TestClient
import app as backend

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(backend,'USERS_DB',tmp_path/'users_test.sqlite')
    with TestClient(backend.app) as cli:yield cli

def test_health_and_source(client):
    m=client.get('/api/meta');assert m.status_code==200
    obj=m.json();assert obj['min_date']=='2026-11-06';assert obj['max_date']=='2026-11-15'
    assert 'North Africa' in obj['regions']
    assert 'Egypt' in obj['regions']['North Africa']
    assert 'Ghana' in obj['regions']['West Africa']
    assert int(obj['dataset']['imported_rows'])==489891
    assert int(obj['dataset']['africa_rows'])==468459
    assert client.get('/api/health').json()['status']=='ok'

def test_dashboard_and_heatmap_real_data(client):
    data=client.get('/api/dashboard').json()
    assert data['summary']['detections']==468459
    assert data['summary']['countries']>=40
    assert sum(day['count'] for day in data['daily'])==468459
    assert sum(x['count'] for x in data['sensors'])==468459
    assert len(data['recent'])>0
    cells=client.get('/api/hotspots').json()
    assert 1<=cells['returned']<=1800
    assert len(cells['cells'])==cells['returned']
    assert cells['resolution_degrees']==.25
    assert all(x['count']>0 for x in cells['cells'])

def test_country_region_date_combination(client):
    allG=client.get('/api/dashboard?region=West%20Africa&country=Ghana').json()['summary']['detections']
    oneG=client.get('/api/dashboard?region=West%20Africa&country=Ghana&start=2026-11-15&end=2026-11-15').json()['summary']['detections']
    assert allG>=oneG>=0
    assert client.get('/api/dashboard?region=North%20Africa&country=Ghana').status_code==422
    assert client.get('/api/dashboard?instrument=FAKE').status_code==422
    assert client.get('/api/dashboard?start=2026-11-15&end=2026-11-06').status_code==422
    assert client.get('/api/dashboard?country=%27%20OR%201%3D1').status_code==422
    assert client.get('/api/dashboard?region=West%20Africa&country=Ghana&start=2050-01-01').json()['summary']['detections']==0

def test_real_auth_and_monitored_sites(client):
    payload={'email':'person@earth.test','password':'testpassword321!','full_name':'Test Scientist','role':'company','company_name':'Test Organization'}
    r=client.post('/api/auth/register',json=payload)
    assert r.status_code==201, r.text
    assert r.json()['account']['role']=='company'
    assert client.get('/api/auth/me').json()['account']['company_name']=='Test Organization'
    created=client.post('/api/areas',json={'name':'Accra area','country':'Ghana','lat':5.6,'lon':-0.2,'radius_km':35,'category':'Timber'})
    assert created.status_code==201,created.text
    areas=client.get('/api/areas').json()['areas']
    assert len(areas)==1
    assert areas[0]['country']=='Ghana'
    assert isinstance(areas[0]['detections'],int)
    assert areas[0]['max_frp']>=0
    assert client.post('/api/areas',json={'name':'Wrong place','country':'Egypt','lat':5.6,'lon':-0.2,'radius_km':35}).status_code==422
    assert client.delete('/api/areas/'+str(areas[0]['id'])).status_code==200
    assert len(client.get('/api/areas').json()['areas'])==0
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/areas').status_code==401
    assert client.post('/api/auth/login',json={'email':payload['email'],'password':payload['password']}).status_code==200

def test_export(client):
    r=client.get('/api/observations.csv?region=West%20Africa&country=Ghana')
    assert r.status_code==200
    assert r.text.startswith('date,country,instrument,detections,max_frp_mw')
    assert 'Ghana' in r.text

def test_static(client):
    assert client.get('/').status_code==200
    assert b'EARTH ON FIRE' in client.get('/').content
    assert client.get('/static/app.js').status_code==200
    assert client.get('/api/countries.geojson').json()['type']=='FeatureCollection'
