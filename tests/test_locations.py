import copy
import json
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient as RealClient
from pydantic import ValidationError
from auth_client import TestClient
from app import auth, db, farm, fields, locations, weather
from app.boundaries import Boundary
from app.identity import current_user
from app.main import app
from test_weather_live import payload

SQUARE={'type':'Polygon','coordinates':[[[29,49],[29.01,49],[29.01,49.01],[29,49.01],[29,49]]]}


def seed_profile(value):
    with db._conn() as c:c.execute('INSERT INTO user_documents VALUES (?,?,?)',(1,'farm_profile.json',json.dumps(value)))


def test_location_merge_and_roundtrip_preserve_profile(tmp_path):
    original={'crops':['кукурудза'],'custom':{'keep':True},'latitude':49,'longitude':29,'location':'old'}
    seed_profile(original)
    with TestClient(app) as client:
        assert client.get('/api/farm/location').json()['location_name']=='old'
        value={'latitude':50.1,'longitude':30.2,'location_name':'Нова ферма'}
        assert client.put('/api/farm/location',json=value).json()==value
        assert client.get('/api/farm').json()['profile']=={**original,**value}
    db.init()
    assert farm.location()==value
    with TestClient(app) as client:
        assert client.put('/api/farm/location',json={'latitude':None,'longitude':None}).status_code==200
        assert client.get('/api/farm/location').json()['latitude'] is None
    assert farm.profile()['crops']==original['crops']


@pytest.mark.parametrize('data',[
 {'latitude':91,'longitude':29},{'latitude':-91,'longitude':29},
 {'latitude':49,'longitude':181},{'latitude':49,'longitude':-181},
 {'latitude':49},{'longitude':29},{'latitude':'NaN','longitude':29},
 {'latitude':'Infinity','longitude':29},{'location_name':'x'*301},
])
def test_invalid_coordinates_do_not_write(data):
    with TestClient(app) as client:assert client.put('/api/farm/location',json=data).status_code==422
    assert farm.profile()=={}


def test_location_api_auth_csrf_and_user_isolation():
    auth.configure('first','password-for-first',create=True)
    auth.configure('second','password-for-second',create=True)
    with RealClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'}) as first,RealClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'}) as second:
        for url in ('/api/farm/location','/api/locations/search?q=Kyiv'):
            assert first.get(url).status_code==401
        assert first.put('/api/farm/location',json={'latitude':49,'longitude':29}).status_code==401
        assert first.post('/auth/login',json={'username':'first','password':'password-for-first'}).status_code==200
        assert second.post('/auth/login',json={'username':'second','password':'password-for-second'}).status_code==200
        assert first.put('/api/farm/location',json={'latitude':49,'longitude':29,'location_name':'private'}).status_code==200
        assert second.get('/api/farm/location').json()['latitude'] is None
        assert second.put('/api/farm/location',json={'latitude':50,'longitude':30}).status_code==200
        assert first.get('/api/farm/location').json()['location_name']=='private'
        assert first.put('/api/farm/location',json={},headers={'Origin':'https://evil.example'}).status_code==403
        field=first.post('/api/fields',json={'name':'private','boundary':SQUARE}).json()['id']
        with patch.object(weather.requests,'get') as upstream:
            assert second.get(f'/api/weather?field_id={field}').status_code==404
            upstream.assert_not_called()


def test_no_point_never_calls_weather_or_uses_climate_fallback():
    with db._conn() as c:c.execute('INSERT INTO user_documents VALUES (?,?,?)',(1,'site/summary.json','{"point":{"latitude":49,"longitude":29}}'))
    with TestClient(app) as client,patch.object(weather.requests,'get') as upstream:
        assert client.get('/api/farm/location').json()['latitude'] is None
        assert client.get('/api/weather').status_code==503
        upstream.assert_not_called()


def test_forecast_uses_saved_point_and_invalidates_changed_coordinates():
    weather._cache=None;weather._retry_at=0
    with TestClient(app) as client,patch.object(weather.requests,'get',return_value=Mock(json=lambda:payload())) as upstream:
        for lat,lon in [(49,29),(50,30)]:
            client.put('/api/farm/location',json={'latitude':lat,'longitude':lon,'location_name':'Ферма'})
            d=client.get('/api/weather').json()
            assert d['requested_point']=={'latitude':lat,'longitude':lon}
            assert d['location']['location_name']=='Ферма'
            assert upstream.call_args.kwargs['params']['latitude']==lat
            assert client.get('/api/weather').status_code==200
        assert upstream.call_count==2
        # Cache metadata must use the current label too.
        client.put('/api/farm/location',json={'latitude':50,'longitude':30,'location_name':'Нова назва'})
        assert client.get('/api/weather').json()['location']['location_name']=='Нова назва'
        assert upstream.call_count==2


def test_fields_polygon_roundtrip_weather_point_and_legacy_payload():
    weather._cache=None;weather._retry_at=0
    with TestClient(app) as client:
        f=client.post('/api/fields',json={'name':'За селом','boundary':SQUARE,'notes':'keep'}).json()
        assert f['boundary']==SQUARE
        assert f['latitude'] is None
        assert client.get('/api/fields').json()[0]['boundary']==SQUARE
        # A legacy client omitting coordinates/boundary must preserve them.
        assert client.put(f"/api/fields/{f['id']}",json={'name':'Нова назва'}).status_code==200
        assert client.get('/api/fields').json()[0]['boundary']==SQUARE
        assert client.get('/api/fields').json()[0]['notes']=='keep'
        with patch.object(weather.requests,'get',return_value=Mock(json=lambda:payload())) as upstream:
            d=client.get(f"/api/weather?field_id={f['id']}").json()
            assert 49<d['requested_point']['latitude']<49.01
            assert 29<d['requested_point']['longitude']<29.01
            assert d['location']['kind']=='field'
            assert d['location']['location_name']=='Нова назва'
        assert client.put(f"/api/fields/{f['id']}",json={'name':'Нова назва','latitude':48,'longitude':28}).status_code==200
        with patch.object(weather.requests,'get',return_value=Mock(json=lambda:payload())):
            assert client.get(f"/api/weather?field_id={f['id']}").json()['requested_point']=={'latitude':48,'longitude':28}
        f2=client.post('/api/fields',json={'name':'Без точки'}).json()
        with patch.object(weather.requests,'get') as upstream:
            assert client.get(f"/api/weather?field_id={f2['id']}").status_code==503
            upstream.assert_not_called()


@pytest.mark.parametrize('ring',[
 [[29,49],[30,49],[29,49]],
 [[29,49],[30,49],[31,49],[29,49]],
 [[29,49],[30,50],[29,50],[30,49],[29,49]],
 [[29,49],[30,49],[30,50],[29,50]],
 [[29,49],[181,49],[30,50],[29,49]],
 [[29,49],[30,49],[30,float('nan')],[29,49]],
])
def test_reject_invalid_boundaries(ring):
    with pytest.raises(ValidationError):Boundary(coordinates=[ring])


def test_concave_polygon_weather_point_is_inside():
    # U shape: bbox center and geometric centroid may be outside.
    boundary=Boundary(coordinates=[[[0,0],[3,0],[3,3],[2,3],[2,1],[1,1],[1,3],[0,3],[0,0]]])
    point=boundary.weather_point()
    x,y=point['longitude'],point['latitude']
    assert 0<x<3 and 0<y<3
    assert y<1 or x<1 or x>2


def test_lookup_is_bounded_and_does_not_save_selected_point():
    raw={'results':[{'name':'Паволоч','admin1':'Житомирська область','country':'Україна','latitude':49.8,'longitude':29.4},
                    {'name':'bad','latitude':999,'longitude':30}]}
    with TestClient(app) as client,patch.object(locations.requests,'get',return_value=Mock(json=lambda:raw)) as upstream:
        data=client.get('/api/locations/search?q=Паволоч').json()
        assert len(data['results'])==1
        assert data['results'][0]['location_name'].startswith('Паволоч')
        assert upstream.call_args.kwargs['params']['count']==8
        assert farm.profile()=={}
        assert client.get('/api/locations/search?q=x').status_code==422
    with TestClient(app) as client,patch.object(locations.requests,'get',side_effect=locations.requests.Timeout('private-secret')):
        r=client.get('/api/locations/search?q=Kyiv')
        assert r.status_code==503
        assert 'private-secret' not in r.text
