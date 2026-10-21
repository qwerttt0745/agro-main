import unittest
from pydantic import ValidationError
from app.farm import nutrient_amount
from app.main import NutrientCalculation
class NutrientTests(unittest.TestCase):
 def test_complex_product_reports_all_components(self):
  r=nutrient_amount(10,30,'P2O5',10,15,20)
  self.assertEqual(r['product_kg_ha'],200)
  self.assertEqual(r['product_total_kg'],2000)
  self.assertEqual(r['nutrients_kg_ha'],{'N':20,'P2O5':30,'K2O':40})
  self.assertIsNone(r['product_l_ha'])
 def test_liquid_mass_and_volume_are_distinct(self):
  r=nutrient_amount(2,32,'N',32,0,0,1.25)
  self.assertEqual(r['product_kg_ha'],100)
  self.assertEqual(r['product_l_ha'],80)
  self.assertEqual(r['product_total_l'],160)
 def test_missing_component(self):
  with self.assertRaises(ValueError):nutrient_amount(1,20,'P2O5',46,0,0)
 def test_input_boundaries(self):
  base=dict(area_ha=1,target_kg_ha=30,basis='N',n_percent=46,p2o5_percent=0,k2o_percent=0)
  for change in [dict(area_ha=-1),dict(n_percent=float('nan')),dict(basis='P'),dict(density_kg_l=0),dict(target_kg_ha=-1)]:
   with self.assertRaises(ValidationError):NutrientCalculation(**(base|change))
