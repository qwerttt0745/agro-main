import json
import unittest
from unittest.mock import Mock, patch
from app import rag

class RepairTests(unittest.TestCase):
    def test_bounded_repair_with_same_deadline(self):
        chunks=[{'id':'S1','source':'a.pdf','page':1,'text':'This is the exact evidence on this page.'}]
        valid=json.dumps({'answer':'Пояснення [S1]','insufficient':False,'evidence':[{'source_id':'S1','quote':chunks[0]['text']}]})
        for second,status in [(valid,'answered'),('bad json','invalid_evidence'),(rag.ServiceUnavailable('timeout'),'invalid_evidence')]:
            with self.subTest(status=status), patch.object(rag,'resources',return_value=Mock()), patch.object(rag,'retrieve',return_value=chunks), patch.object(rag,'_generate',side_effect=['bad json',second]) as generate:
                result=rag.answer('Question')
                self.assertEqual(result['status'],status)
                self.assertEqual(generate.call_count,2)
                self.assertEqual(generate.call_args_list[0].kwargs['deadline'],generate.call_args_list[1].kwargs['deadline'])

    def test_valid_answer_not_retried(self):
        raw=json.dumps({'answer':'','insufficient':True,'evidence':[]})
        with patch.object(rag,'resources',return_value=Mock()), patch.object(rag,'retrieve',return_value=[{'id':'S1','source':'a.pdf','page':1,'text':'text'}]), patch.object(rag,'_generate',return_value=raw) as generate:
            self.assertEqual(rag.answer('Question')['status'],'insufficient')
            self.assertEqual(generate.call_count,1)

    def test_repair_keeps_original_question_and_dialogue(self):
        history=[{'role':'user','content':'Хочу посіяти гречку після пшениці'}]
        chunks=[{'id':'S1','source':'a.pdf','page':1,'text':'This is the exact evidence on this page.'}]
        with patch.object(rag,'resources',return_value=Mock()), patch.object(rag,'retrieve',return_value=chunks), patch.object(rag,'standalone_question',return_value='Коли сіяти гречку?'), patch.object(rag,'_generate',side_effect=['bad json','bad json']) as gen:
            rag.answer('А після збору врожаю?',history)
            repair=gen.call_args.args[0]
            self.assertIn('А після збору врожаю?',repair)
            self.assertIn('Хочу посіяти гречку після пшениці',repair)
