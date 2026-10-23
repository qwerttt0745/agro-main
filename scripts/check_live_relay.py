"""Real provider smoke via ASGI WebSocket, synthetic image, no user media."""
import base64
import io
import json
import tempfile
import time
import sys
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from app import auth,live,db
from app.main import app


def main():
    image=io.BytesIO();Image.new('RGB',(320,240),'red').save(image,format='JPEG')
    tool_check='--weather' in sys.argv
    turn=0
    first_text_length=0
    report={'weather_tool_called':False,'audio_bytes':0,'transcript':'','ready':False,'frame_sent':False}
    started=time.monotonic()
    with tempfile.TemporaryDirectory() as directory,patch.object(auth,'CREDENTIALS',Path(directory)/'credentials.json'),patch.object(auth,'DATABASE',Path(directory)/'auth.db'),patch.object(db,'DB',Path(directory)/'chats.db'),patch.dict('os.environ',{'AGRO_COOKIE_SECURE':'false','AGRO_PUBLIC_ORIGIN':'http://testserver'}),patch.object(live,'MAX_SECONDS',40):
        auth.configure('smoke','temporary-test-password',create=True)
        db.init()
        if tool_check:
            with db._conn() as c:c.execute('INSERT INTO user_documents VALUES (?,?,?)',(1,'farm_profile.json',json.dumps({'latitude':49.8,'longitude':29.4})))
        with TestClient(app) as client:
            r=client.post('/auth/login',json={'username':'smoke','password':'temporary-test-password'},headers={'X-Agro-Request':'1','Origin':'http://testserver'})
            assert r.status_code==200
            with client.websocket_connect('/api/live',headers={'origin':'http://testserver'}) as ws:
                while True:
                    message=ws.receive_json();kind=message['type']
                    if kind=='ready':
                        report['ready']=True
                        ws.send_json({'type':'video','data':base64.b64encode(image.getvalue()).decode()});report['frame_sent']=True
                        time.sleep(1)
                        ws.send_json({'type':'text','text':'Якого кольору кадр? Відповідай одним реченням українською.'})
                    elif kind=='audio':report['audio_bytes']+=len(base64.b64decode(message['data']))
                    elif kind=='transcript':report['transcript']+=message['text']
                    elif kind=='status':
                        if 'погоду' in message.get('message',''):report['weather_tool_called']=True
                    elif kind=='turn_complete':
                        turn+=1
                        if tool_check and turn==1:
                            first_text_length=len(report['transcript'])
                            ws.send_json({'type':'text','text':'Використай farm_weather та скажи прогноз температури для господарства на завтра.'})
                        elif not tool_check or (report['weather_tool_called'] and len(report['transcript'])>first_text_length):
                            report['weather_answer_received']=tool_check
                            ws.send_json({'type':'stop'});break
                    elif kind=='error':report['error']=message['message'];break
    report['seconds']=round(time.monotonic()-started,2)
    report['ok']=report['ready'] and report['audio_bytes']>0 and 'червон' in report['transcript'].lower() and (not tool_check or report.get('weather_answer_received',False))
    Path('evaluation/live-relay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(report)
    return int(not report['ok'])

if __name__=='__main__':raise SystemExit(main())
