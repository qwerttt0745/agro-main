import asyncio
import base64
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import weather, live, rag
from app.main import app


def payload():
    day=datetime.now(ZoneInfo('Europe/Kyiv')).date().isoformat()
    return {'daily':{'time':[day],**{k:[None if k=='precipitation_sum' else 3] for k in ['temperature_2m_min','temperature_2m_max','precipitation_sum','precipitation_probability_max','wind_speed_10m_max','wind_gusts_10m_max']}},'current':{},'current_units':{},'hourly':{},'hourly_units':{},'daily_units':{}}

class WeatherTests(unittest.TestCase):
    def setUp(self):
        weather._cache=None;weather._retry_at=0
    def test_cache_coordinates_and_missing_values(self):
        with patch.object(weather.requests,'get',return_value=Mock(json=lambda:payload())) as get:
            first=weather.forecast();weather.forecast();self.assertEqual(get.call_count,1)
            self.assertEqual(get.call_args.kwargs['params']['wind_speed_unit'],'ms')
            self.assertIn('немає даних',weather.answer('Буде дощ?')['answer'])
            first['days'][0]['date']='corrupted'
            self.assertNotEqual(weather.forecast()['days'][0]['date'],'corrupted')
    def test_bad_forecast_not_served_as_current(self):
        data=payload();data['daily']['time']=['2001-01-01']
        with patch.object(weather.requests,'get',return_value=Mock(json=lambda:data)) as get:
            for _ in range(2):
                with self.assertRaises(weather.WeatherUnavailable):weather.forecast()
            self.assertEqual(get.call_count,1)
    def test_weather_skips_gemini_and_index(self):
        with patch.object(weather,'forecast',return_value={**payload(),'days':[],'note':'Forecast','retrieved_at':'now'}),patch.object(rag,'_generate') as gen,patch.object(rag,'resources') as resources:
            self.assertEqual(rag.answer('Яка погода завтра?')['status'],'weather')
            gen.assert_not_called();resources.assert_not_called()
        self.assertFalse(weather.simple_question('Чи можна обприскувати сою, якщо завтра дощ?'))
    def test_complete_crop_question_skips_rewrite(self):
        with patch.object(rag,'_generate') as gen:
            q='Яка глибина загортання насіння озимої пшениці на важких ґрунтах?'
            self.assertEqual(rag.standalone_question(q,[{'role':'user','content':'Привіт'}]),q)
            gen.assert_not_called()

class LiveTests(unittest.TestCase):
    def test_media_limits(self):
        self.assertEqual(live.decode_media({'data':base64.b64encode(b'ab').decode()},2),b'ab')
        for value in ['', 'not base64',base64.b64encode(b'abc').decode()]:
            with self.assertRaises(ValueError):live.decode_media({'data':value},2)
    def test_origin_and_auth_both_required(self):
        ws=SimpleNamespace(base_url='ws://testserver/',headers={'origin':'http://evil'},cookies={})
        with patch.dict('os.environ',{'AGRO_PUBLIC_ORIGIN':'http://testserver'}),patch.object(live.auth,'authenticated',return_value=True):
            self.assertFalse(live.allowed(ws));ws.headers['origin']='http://testserver';self.assertTrue(live.allowed(ws))
        with patch.object(live.auth,'authenticated',return_value=False):self.assertFalse(live.allowed(ws))
    def test_websocket_rejects_anonymous(self):
        with TestClient(app) as client,patch.object(live.auth,'authenticated',return_value=False):
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/live',headers={'origin':'http://testserver'}):pass
    def test_tool_whitelist(self):
        result=asyncio.run(live.tool_result('execute_shell',{}));self.assertIn('error',result)
        self.assertIn('error',asyncio.run(live.tool_result('farm_library',{'question':'x'*2001})))
    def test_relay_cleanup_on_stop(self):
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def receive(self):
                await asyncio.sleep(100)
                if False:yield None
        client=SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=lambda **kwargs:Session()),aclose=AsyncMock()))
        with TestClient(app) as web,patch.object(live,'allowed',return_value=True),patch.object(live.genai,'Client',return_value=client):
            with web.websocket_connect('/api/live') as ws:
                self.assertEqual(ws.receive_json()['type'],'ready')
                ws.send_json({'type':'stop'})
                with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        self.assertFalse(live._active);client.aio.aclose.assert_awaited_once()

    def test_relay_forwards_audio_video_text_and_cleans_up(self):
        calls=[]
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def send_realtime_input(self,**kw):calls.append(kw)
            async def receive(self):
                await asyncio.sleep(100)
                if False:yield None
        client=SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=lambda **kwargs:Session()),aclose=AsyncMock()))
        with TestClient(app) as web,patch.object(live,'allowed',return_value=True),patch.object(live.genai,'Client',return_value=client):
            with web.websocket_connect('/api/live') as ws:
                ws.receive_json()
                ws.send_json({'type':'audio','data':base64.b64encode(b'\x00\x00'*1600).decode()})
                ws.send_json({'type':'video','data':base64.b64encode(b'\xff\xd8test').decode()})
                ws.send_json({'type':'text','text':'Привіт'})
                ws.send_json({'type':'mute'})
                ws.send_json({'type':'stop'})
                with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        self.assertEqual([next(iter(c)) for c in calls],['audio','video','text','audio_stream_end'])
        self.assertEqual(calls[0]['audio'].mime_type,'audio/pcm;rate=16000')
        self.assertFalse(live._active)
