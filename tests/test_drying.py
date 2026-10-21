import unittest
from unittest.mock import patch
from app import intent,rag
Q='• Фізична (початкова) вага: 25 000 кг (25 тонн)\n• Фактична вологість зерна: 24,5%\n• Базова (цільова) вологість за стандартом: 14,0%'
class DryingTests(unittest.TestCase):
 def test_mass_balance(self):
  r=intent.drying_answer(Q)
  self.assertIn('21947,67',r['answer']);self.assertIn('3052,33',r['answer'])
 def test_photo_does_not_override_calculation(self):
  with patch.object(rag,'_generate',side_effect=AssertionError('Unnecessary model call')):
   self.assertEqual(rag.answer_photo(Q,b'photo'),rag.answer(Q))
 def test_missing_or_invalid_measurements(self):
  self.assertIsNone(intent.drying_answer('Вологість землі 27%'))
  self.assertIsNone(intent.drying_answer(Q.split('\n')[0]))
  self.assertEqual(intent.drying_answer(Q.replace('24,5%','10%'))['status'],'needs_field_data')
