import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from fastapi import HTTPException
from app import db,fields
class FieldTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(db,'DB',Path(self.tmp.name)/'db');self.p.start()
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_optional_values_remain_unknown_and_edit_persists(self):
  r=fields.save(fields.FieldRecord(name='За селом'))
  self.assertIsNone(r['area_ha']);self.assertEqual(fields.records()[0]['soil'],'')
  fields.save(fields.FieldRecord(name='За селом',area_ha=10,crop='соя 2026'),r['id'])
  self.assertEqual(len(fields.records()),1);self.assertEqual(fields.records()[0]['area_ha'],10)
  self.assertIn('соя 2026',fields.context('План для поля За селом'))
  self.assertNotIn('соя 2026',fields.context('Інше поле'))
 def test_invalid_values_and_unknown_record(self):
  for data in [dict(name=' '),dict(name='Поле',area_ha=-1),dict(name='Поле',area_ha=float('nan'))]:
   with self.assertRaises(ValidationError):fields.FieldRecord(**data)
  with self.assertRaises(HTTPException):fields.save(fields.FieldRecord(name='Поле'),999)
