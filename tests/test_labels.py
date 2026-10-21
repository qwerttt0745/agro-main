import unittest,tempfile,base64,io
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi import HTTPException
from app import db,labels
class LabelTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(db,'DB',Path(self.tmp.name)/'db');self.p.start()
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_upload_private_image_list_and_delete(self):
  b=io.BytesIO();Image.new('RGB',(30,30),'white').save(b,format='PNG')
  r=labels.upload(labels.LabelUpload(name='Препарат',photo=base64.b64encode(b.getvalue()).decode()))
  self.assertEqual(r['status'],'unverified');self.assertNotIn('image',labels.listing()[0])
  self.assertEqual(labels.image(r['id']).media_type,'image/jpeg')
  labels.remove(r['id']);self.assertEqual(labels.listing(),[])
  with self.assertRaises(HTTPException):labels.image(r['id'])
 def test_reject_invalid_photo(self):
  with self.assertRaises(HTTPException):labels.upload(labels.LabelUpload(name='Назва',photo='bad'))
  self.assertEqual(labels.listing(),[])
