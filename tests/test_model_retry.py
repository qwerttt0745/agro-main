import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from auth_client import TestClient
from app import db, rag
from app.main import app

class RetryTests(unittest.TestCase):
    def test_retry_reuses_saved_message_and_photo(self):
        from test_photos import picture
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db.sqlite'),TestClient(app) as client:
            chat=client.post('/chats').json()['id']
            with patch.object(rag,'answer_photo',side_effect=rag.ServiceUnavailable('Недоступно')):
                r=client.post(f'/chats/{chat}/ask',json={'text':'Фото','photo':picture()})
                self.assertEqual(r.status_code,200);self.assertTrue(r.json()['retryable'])
            before=db.get_messages(chat)
            with patch.object(rag,'answer_photo',return_value={'answer':'Опис','pages':[],'sources':[],'status':'photo_observation'}) as answer:
                r=client.post(f'/chats/{chat}/retry')
            self.assertEqual(r.json()['answer'],'Опис')
            self.assertTrue(answer.call_args.args[1].startswith(b'\xff\xd8'))
            after=db.get_messages(chat);self.assertEqual(len(after),2);self.assertEqual(before[0],after[0])
            self.assertEqual(client.post(f'/chats/{chat}/retry').status_code,409)
            self.assertEqual(client.post('/chats/99999/retry').status_code,404)

    def test_config_error_is_not_presented_as_retryable(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db.sqlite'),TestClient(app) as client:
            chat=client.post('/chats').json()['id']
            with patch.object(rag,'answer',side_effect=rag.ServiceUnavailable('Налаштування',502)):
                r=client.post(f'/chats/{chat}/ask',json={'text':'Question'})
            self.assertFalse(r.json()['retryable'])
