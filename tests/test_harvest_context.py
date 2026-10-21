import unittest,json
from datetime import date
from unittest.mock import patch
from app import rag,weather
class HarvestContextTests(unittest.TestCase):
 def test_tuesday_is_exact_date(self):
  self.assertEqual(weather.requested_day('наступний вівторок',date(2026,10,21)),date(2026,10,27))
  self.assertTrue(weather.needs_context('Чи можна збирати кукурудзу наступного вівторка?'))
 def test_photo_preserves_question_and_history(self):
  observation={'usable':True,'possible_identity':'Кукурудза','observations':['Виповнені зерна'],'questions':[],'search_query':'кукурудза стиглість'}
  history=[{'role':'user','content':'Сушарка є, вологість землі 27%'}]
  with patch.object(rag,'_generate',return_value=json.dumps(observation)),patch.object(rag,'answer',return_value={'answer':'Рішення на вівторок','pages':[],'sources':[],'searched_as':'кукурудза'}) as answer:
   result=rag.answer_photo('Чи можна збирати у вівторок?',b'jpeg',history)
   self.assertEqual(answer.call_args.args[0],'Чи можна збирати у вівторок?')
   self.assertEqual(answer.call_args.kwargs['history'],history)
   self.assertIn('Виповнені зерна',answer.call_args.kwargs['photo_context'])
   self.assertTrue(result['answer'].startswith('Рішення на вівторок'))
