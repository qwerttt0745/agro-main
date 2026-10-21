import json
import unittest
from auth_client import TestClient
from app.main import app
from app import rag, farm

class FarmTests(unittest.TestCase):
    def test_mass_balance(self):
        result = TestClient(app).post('/api/calculations/nitrogen', json={'area_ha':10,'target_n_kg_ha':46,'n_percent':46})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['product_total_kg'],1000)
        self.assertEqual(result.json()['product_kg_ha'],100)

    def test_invalid_values(self):
        for key,value in [('area_ha',0),('area_ha',-1),('n_percent',0),('n_percent',101),('n_percent',1e-300),('target_n_kg_ha',-1),('n_percent','NaN'),('area_ha','Infinity')]:
            payload={'area_ha':10,'target_n_kg_ha':46,'n_percent':46};payload[key]=value
            with self.subTest(key=key,value=value):
                self.assertEqual(TestClient(app).post('/api/calculations/nitrogen',json=payload).status_code,422)

    def test_zero_n(self):
        self.assertEqual(farm.nitrogen_amount(10,0,46)['product_total_kg'],0)

    def test_no_prescription_when_flagged(self):
        for flag,status in [('pesticide_application','label_required'),('needs_field_data','field_data_required')]:
            raw=json.dumps({'answer':'Неперевірена доза','insufficient':False,'evidence':[],flag:True})
            result=rag.validate_answer(raw,[],'Питання')
            self.assertEqual(result['status'],status)
            self.assertNotIn('Неперевірена доза',result['answer'])
            self.assertEqual(result['sources'],[])
