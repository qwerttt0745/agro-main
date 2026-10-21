import unittest
from decimal import Decimal
from app import intent,rag
from unittest.mock import patch

class IntentTests(unittest.TestCase):
    def test_seed_quantity_units_and_question_intent(self):
        self.assertEqual(intent.seed_mass('Яку площу гречки засіяти якщо в мене 300 г'),Decimal('0.3'))
        self.assertEqual(intent.seed_mass('Яку площу гречки засіяти 0,3 кг'),Decimal('0.3'))
        self.assertIsNone(intent.seed_mass('Яку площу гречки засіяти 300 га'))
        self.assertIn('норма висіву',intent.search_terms('Яку площу гречки засіяти з 300 г'))

    def test_seed_answer_calculates_from_verified_passage(self):
        chunks=[{'id':'S2','source':'TVPR_2_2010.pdf','page':83,'text':'Норма висіву за звичайного рядкового способу сівби у зоні Лісостепу і на Поліссі на 1 гектар висівають 80-100 кг/га або 3-3,5 млн зерен; у разі широкорядної сівби – 50-80 кг/га.'}]
        q='Яку площу гречки засіяти цього року якщо в мене всього 300 г'
        result=intent.seed_answer(q,chunks)
        self.assertIn('30–37,5 м²',result['answer']);self.assertIn('37,5–60 м²',result['answer'])
        self.assertNotIn('тис. га',result['answer'])
        import json
        self.assertEqual(rag.validate_answer(json.dumps(result),chunks,q)['status'],'answered')
        self.assertIsNone(intent.seed_answer(q,[{**chunks[0],'text':'У світі сіють 2,7 млн га гречки.'}]))

    def test_local_soil_does_not_guess_or_need_api(self):
        with patch.object(rag,'_generate') as generate:
            result=rag.answer('я зараз на полі біля бази який тут вид землі чорнозем?')
            self.assertIn('не можна підтвердити',result['answer']);generate.assert_not_called()
        self.assertFalse(intent.soil_question('Що таке чорнозем?'))

    def test_followup_keeps_history_and_original_topic(self):
        history=[{'role':'user','content':'Буду сіяти гречку, який сорт?'},{'role':'assistant','content':'Уточніть місцевість.'}]
        with patch.object(rag,'_generate',return_value='Який сорт гречки обрати для Паволочі?') as gen:
            self.assertIn('гречки',rag.standalone_question('а для Паволочі?',history))
            self.assertIn('Буду сіяти гречку',gen.call_args.args[0])

    def test_followup_after_provider_failure_keeps_user_history(self):
        history=[{'role':'user','content':'Коли сіяти гречку?'}]
        with patch.object(rag,'_generate',return_value='Коли сіяти гречку в Паволочі?') as gen:
            self.assertIn('гречку',rag.standalone_question('А в Паволочі?',history))
            self.assertIn('Коли сіяти гречку?',gen.call_args.args[0])

    def test_explicit_mass_bypasses_model_rewrite(self):
        from unittest.mock import Mock
        chunks=[{'id':'S2','source':'TVPR_2_2010.pdf','page':83,'text':'Норма висіву за звичайного рядкового способу 80-100 кг/га; широкорядної сівби – 50-80 кг/га.'}]
        history=[{'role':'user','content':'Маю 300 гектарів'},{'role':'assistant','content':'Яка культура?'}]
        with patch.object(rag,'resources',return_value=Mock()), patch.object(rag,'retrieve',return_value=chunks), patch.object(rag,'_generate') as gen:
            result=rag.answer('Яку площу гречки засіяти з 300 г?',history)
            self.assertIn('30–37,5 м²',result['answer'])
            gen.assert_not_called()
