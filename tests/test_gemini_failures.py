import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from google.genai import errors
from app import rag, model_pool

class GeminiFailureTests(unittest.TestCase):
    def setUp(self):
        self.state = patch.object(model_pool, '_state', {})
        self.state.start();self.addCleanup(self.state.stop)

    def test_switch_all_five_without_repeating(self):
        client=Mock();client.models.generate_content.side_effect=[errors.ServerError(503,{'message':'busy'})]*4+[SimpleNamespace(text='ok')]
        with patch.object(rag,'llm_client',return_value=client):self.assertEqual(rag._generate('q'),'ok')
        self.assertEqual([c.kwargs['model'] for c in client.models.generate_content.call_args_list],list(model_pool.MODELS))
        self.assertEqual(model_pool.candidates(),[model_pool.MODELS[-1]])

    def test_quota_delay_and_recovery(self):
        first=model_pool.MODELS[0]
        error=errors.ClientError(429,{'error':{'message':'quota','details':[{'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'7200s'}]}})
        with patch.object(model_pool.time,'time',return_value=100):model_pool.failure(first,'quota',error)
        with patch.object(model_pool.time,'time',return_value=101):
            self.assertNotIn(first,model_pool.candidates());self.assertEqual(model_pool.status()[0]['retry_after'],7199)
        with patch.object(model_pool.time,'time',return_value=7301):self.assertIn(first,model_pool.candidates())

    def test_quota_and_missing_model_switch(self):
        for code in (429,403,404):
            model_pool._state.clear()
            client=Mock();client.models.generate_content.side_effect=[errors.ClientError(code,{'message':'failure'}),SimpleNamespace(text='ok')]
            with patch.object(rag,'llm_client',return_value=client):self.assertEqual(rag._generate('q'),'ok')
            self.assertEqual(client.models.generate_content.call_count,2)

    def test_global_key_and_request_errors_stop(self):
        for code in (400,401):
            client=Mock();client.models.generate_content.side_effect=errors.ClientError(code,{'message':'bad'})
            with patch.object(rag,'llm_client',return_value=client),self.assertRaises(rag.ServiceUnavailable):rag._generate('q')
            self.assertEqual(client.models.generate_content.call_count,1)

    def test_deadline_and_cooldown_do_not_call_provider(self):
        client=Mock()
        with patch.object(rag,'llm_client',return_value=client),self.assertRaises(rag.ServiceUnavailable):rag._generate('q',deadline=0)
        client.models.generate_content.assert_not_called()
        for model in model_pool.MODELS:model_pool.failure(model,'overloaded')
        with patch.object(rag,'llm_client',return_value=client),self.assertRaises(rag.ServiceUnavailable):rag._generate('q')
        client.models.generate_content.assert_not_called()

    def test_empty_and_network_failures_switch(self):
        import httpx
        client=Mock();client.models.generate_content.side_effect=[SimpleNamespace(text=''),httpx.ReadTimeout('timeout'),SimpleNamespace(text='ok')]
        with patch.object(rag,'llm_client',return_value=client):self.assertEqual(rag._generate('q'),'ok')
        self.assertEqual(client.models.generate_content.call_count,3)

    def test_all_overloaded_are_bounded(self):
        client=Mock();client.models.generate_content.side_effect=errors.ServerError(503,{'message':'busy'})
        with patch.object(rag,'llm_client',return_value=client),self.assertRaises(rag.ServiceUnavailable):rag._generate('q')
        self.assertEqual(client.models.generate_content.call_count,5)
        self.assertEqual(model_pool.candidates(),[])

    def test_failed_questions_do_not_require_rewrite(self):
        with patch.object(rag,'_generate') as generate:
            self.assertEqual(rag.standalone_question('q',[{'role':'user','content':'q'}]),'q');generate.assert_not_called()
