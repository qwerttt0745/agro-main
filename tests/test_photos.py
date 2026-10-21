import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from auth_client import TestClient
from app import photos, db, rag
from app.main import app

def picture():
    im=Image.new('RGB',(200,100),'green'); exif=Image.Exif();exif[270]='private metadata'
    out=io.BytesIO();im.save(out,format='JPEG',exif=exif)
    return base64.b64encode(out.getvalue()).decode()

class PhotosTests(unittest.TestCase):
    def test_strip_metadata_and_validate(self):
        clean=photos.prepare(picture())
        with Image.open(io.BytesIO(clean)) as im:
            self.assertEqual(im.size,(200,100));self.assertFalse(im.getexif())
        for raw in ['bad!',base64.b64encode(b'<svg>bad</svg>').decode()]:
            with self.assertRaises(ValueError):photos.prepare(raw)
        with patch.object(photos,'MAX_PIXELS',10), self.assertRaises(ValueError):photos.prepare(picture())
        with patch.object(photos,'MAX_BYTES',10), self.assertRaises(ValueError):photos.prepare(picture())

    def test_photo_survives_provider_failure_and_is_scoped_to_chat(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB',Path(tmp)/'db.sqlite'), TestClient(app) as client:
            chat=client.post('/chats').json()['id'];other=client.post('/chats').json()['id']
            with patch.object(rag,'answer_photo',side_effect=rag.ServiceUnavailable('Unavailable')):
                response=client.post(f'/chats/{chat}/ask',json={'text':'Фото','photo':picture()})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['status'],'unavailable')
            messages=client.get(f'/chats/{chat}').json();self.assertEqual(len(messages),1)
            url=messages[0]['photo_url'];image=client.get(url)
            self.assertEqual(image.status_code,200)
            self.assertEqual(image.headers['content-type'],'image/jpeg')
            self.assertEqual(client.get(url.replace(f'/chats/{chat}/',f'/chats/{other}/')).status_code,404)
            self.assertEqual(client.post(f'/chats/{chat}/ask',json={'text':'bad','photo':'not image'}).status_code,422)
            self.assertEqual(len(client.get(f'/chats/{chat}').json()),1)
            db.init();self.assertEqual(client.get(url).status_code,200)

    def test_vision_does_not_search_unusable_image(self):
        raw=json.dumps({'usable':False,'observations':['Немає рослини'],'questions':['Надішліть фото листка'],'search_query':''})
        with patch.object(rag,'_generate',return_value=raw),patch.object(rag,'answer') as answer:
            result=rag.answer_photo('Question',b'jpeg')
            answer.assert_not_called();self.assertEqual(result['sources'],[])

    def test_vision_and_library_share_deadline(self):
        raw=json.dumps({'usable':True,'observations':['Жовта ділянка'],'questions':[],'search_query':'жовте листя'})
        with patch.object(rag,'_generate',return_value=raw) as gen,patch.object(rag,'answer',side_effect=rag.ServiceUnavailable('timeout')) as answer:
            result=rag.answer_photo('Question',b'jpeg')
            self.assertEqual(gen.call_args.kwargs['deadline'],answer.call_args.kwargs['deadline'])
            self.assertIn('Жовта ділянка',result['answer']);self.assertEqual(result['sources'],[])
