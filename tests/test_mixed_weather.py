import json
import unittest
from unittest.mock import Mock,patch
from app import rag,weather,intent

QUESTION='яка зараз погода в паволочі? чи підійде зараз молотитьь кукурудзу?'
BOOK={'id':'S1','source':'book.pdf','page':12,'text':'Для збирання кукурудзи потрібно визначити вологість зерна.'}
SNAPSHOT={'id':'S2','source':'Open-Meteo','page':None,'kind':'weather','retrieved_at':'2026-10-21T05:00:00+00:00','text':'Прогноз на сьогодні: опади за добу 0 мм, імовірність опадів 18 %.'}

class MixedWeatherTests(unittest.TestCase):
 def test_corn_harvest_excludes_generic_cereal_maturity(self):
  generic={'id':'S2','text':'Повна стиглість зерна. Вологість 14-20%'}
  self.assertEqual(intent.relevant_chunks(QUESTION,[BOOK,generic]),[BOOK])
  self.assertEqual(intent.relevant_chunks('Що таке повна стиглість зернових?',[generic]),[generic])
 def test_work_questions_never_short_circuit_to_forecast(self):
  for q in [QUESTION,'Яка погода, можна збирати сою?','Чи можна молотити кукурудзу зараз?','Який вітер, чи можна їхати комбайном на поле?']:
   self.assertFalse(weather.simple_question(q));self.assertTrue(weather.needs_context(q))
  self.assertTrue(weather.simple_question('Яка зараз погода в Паволочі?'))
  self.assertIn('вологість зерна',intent.search_terms(QUESTION))
 def test_both_sources_reach_answer_and_are_validated(self):
  raw=json.dumps({'answer':'За прогнозом без опадів [S2], але потрібна вологість зерна [S1].','insufficient':False,'evidence':[{'source_id':'S1','quote':BOOK['text']},{'source_id':'S2','quote':SNAPSHOT['text']}]})
  with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'retrieve',return_value=[BOOK.copy()]),patch.object(weather,'context_chunk',return_value=SNAPSHOT.copy()),patch.object(rag,'_generate',return_value=raw) as gen:
   result=rag.answer(QUESTION)
   self.assertEqual(result['status'],'answered');self.assertEqual(result['pages'],[12])
   self.assertIn(BOOK['text'],gen.call_args.args[0]);self.assertIn(SNAPSHOT['text'],gen.call_args.args[0]);self.assertIn(QUESTION,gen.call_args.args[0])
   self.assertEqual(result['sources'][1]['url'],'https://open-meteo.com/')
 def test_weather_outage_does_not_erase_work_question(self):
  raw=json.dumps({'answer':'Немає поточного прогнозу; потрібна вологість зерна [S1].','insufficient':False,'evidence':[{'source_id':'S1','quote':BOOK['text']}]})
  with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'retrieve',return_value=[BOOK.copy()]),patch.object(weather,'context_chunk',side_effect=weather.WeatherUnavailable('offline')),patch.object(rag,'_generate',return_value=raw) as gen:
   result=rag.answer(QUESTION)
   self.assertIn('API недоступний',gen.call_args.args[0]);self.assertIn('вологість',result['answer'])
 def test_fabricated_weather_quote_rejected(self):
  raw=json.dumps({'answer':'Дощ гарантовано відсутній [S2].','insufficient':False,'evidence':[{'source_id':'S2','quote':'Дощ гарантовано відсутній протягом дня.'}]})
  self.assertEqual(rag.validate_answer(raw,[SNAPSHOT],QUESTION)['status'],'invalid_evidence')
 def test_short_followup_keeps_work_context(self):
  raw=json.dumps({'answer':'Потрібна вологість зерна [S1].','insufficient':False,'evidence':[{'source_id':'S1','quote':BOOK['text']}]})
  with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'standalone_question',return_value='Чи можна молотити кукурудзу завтра?') as rewrite,patch.object(rag,'retrieve',return_value=[BOOK.copy()]),patch.object(weather,'context_chunk',return_value=SNAPSHOT.copy()) as forecast,patch.object(rag,'_generate',return_value=raw):
   rag.answer('а завтра?',history=[{'role':'user','content':QUESTION}]);rewrite.assert_called_once();forecast.assert_called_once()
