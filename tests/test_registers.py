import io
import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
from app import registers,rag

class RegisterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(registers,'DB',Path(self.tmp.name)/'r.db');self.p.start()
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def seed(self):
  c=registers.connect()
  with c:
   c.execute('INSERT INTO snapshots VALUES (?,?)',('pesticides',json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),'as_of':'2026-10-19','rows':1})))
   c.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',('pesticides','2020',2,'Препарат А',registers.normalized('Препарат А'),json.dumps({'name':'Препарат А','number':'12','expires':'2029-12-31'})))
  c.close()
 def test_casefold_and_wildcards(self):
  self.seed();self.assertEqual(registers.search('pesticides','ПРЕПАРАТ',False)['total'],1)
  self.assertEqual(registers.search('pesticides','%%',False)['total'],0)
 def test_freshness_is_separate_from_publication_date(self):
  now=datetime.now(timezone.utc)
  self.assertTrue(registers.fresh({'checked_at':now.isoformat(),'as_of':'2000-01-01'}))
  self.assertFalse(registers.fresh({'checked_at':(now-timedelta(days=2)).isoformat()}))
  self.assertFalse(registers.fresh({'checked_at':now.isoformat(),'error':'Timeout'}))
  self.assertFalse(registers.fresh({'checked_at':(now+timedelta(days=1)).isoformat()}))
 def test_failed_refresh_preserves_rows_but_marks_unverified(self):
  self.seed()
  with patch.object(registers,'fetch',side_effect=ValueError('bad format')):registers.refresh('pesticides',True)
  result=registers.search('pesticides','Препарат',False)
  self.assertEqual(result['total'],1);self.assertFalse(result['fresh_check'])
 def test_cancellation_beats_future_expiry(self):
  self.assertIn('скасування',registers.row_status('pesticides',{'expires':'2030-12-31','notes':'Анульовано'}))
  self.assertIn('минув',registers.row_status('pesticides',{'expires':'2000-12-31'}))
  self.assertIn('Виключений',registers.row_status('varieties',{'section':'excluded'}))
 def test_import_legacy_columns_and_row_provenance(self):
  w=Workbook();s=w.active;s.title='Old';s.append(['registration_number','name','registration_certificate','scope','expiration_date','примітки']);s.append([1,'Назва','A1','культура',datetime(2029,12,31),'Анульовано'])
  stream=io.BytesIO();w.save(stream);w.close();r=registers.parse_book(stream.getvalue(),'pesticides')
  self.assertEqual(r[0][1:3],('Old',2));self.assertEqual(json.loads(r[0][-1])['expires'],'2029-12-31')
 def test_registry_command_bypasses_llm(self):
  self.seed()
  with patch.object(rag,'_generate') as gen:
   result=rag.answer('Перевір препарат: Препарат А')
   self.assertEqual(result['status'],'registry_lookup');gen.assert_not_called()
  self.assertIsNone(registers.query_intent('Який сорт найкращий?'))
 def test_multiple_terms_are_combined_not_one_phrase(self):
  self.seed();self.assertEqual(registers.search('pesticides','А препарат',False)['total'],1)
 def test_natural_registration_question(self):
  self.assertEqual(registers.query_intent('Чи зареєстрований сорт Вікторія?'),('varieties','Вікторія'))
 def test_changed_schema_is_rejected(self):
  w=Workbook();w.active.append(['unknown column']);w.active.append(['not a record']);b=io.BytesIO();w.save(b);w.close()
  with self.assertRaises(ValueError):registers.parse_book(b.getvalue(),'pesticides')

 def test_current_records_precede_archive_before_limit(self):
  self.seed();c=registers.connect()
  with c:
   for i in range(25):
    payload={'name':'Препарат А','number':str(i),'expires':'2000-12-31'}
    c.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',('pesticides','Old',i+100,'Препарат А','препарат а',json.dumps(payload)))
  c.close()
  r=registers.search('pesticides','Препарат А',False)
  self.assertEqual(r['total'],26);self.assertEqual(r['historical_total'],25)
  self.assertEqual(r['items'][0]['number'],'12');self.assertFalse(r['items'][0]['historical'])
  self.assertEqual(r['shown'],20)
