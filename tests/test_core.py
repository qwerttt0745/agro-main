import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from auth_client import TestClient
from app import db, rag
from app.main import app
from scripts.ingest import ingest, split


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, 'DB', Path(self.tmp.name) / 'nested/chats.db')
        self.db_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.chat_id = self.client.post('/chats').json()['id']

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_startup_and_history_without_current_question(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        answer = {'answer': 'Відповідь (книга.pdf, стор. 3)', 'pages': [3]}
        with patch.object(rag, 'answer', return_value=answer) as generate:
            self.assertEqual(self.client.post(f'/chats/{self.chat_id}/ask', json={'text': 'Перше?'}).status_code, 200)
            self.assertEqual(generate.call_args.args, ('Перше?', []))
            self.client.post(f'/chats/{self.chat_id}/ask', json={'text': 'Друге?'})
            self.assertEqual([m['role'] for m in generate.call_args.args[1]], ['user', 'assistant'])
        history = self.client.get(f'/chats/{self.chat_id}').json()
        self.assertEqual(len(history), 4)
        self.assertEqual(history[1]['pages'], [3])

    def test_failure_preserves_question(self):
        with patch.object(rag, 'answer', side_effect=rag.ServiceUnavailable('Питання збережено')):
            result = self.client.post(f'/chats/{self.chat_id}/ask', json={'text': 'Важливе питання'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'unavailable')
        self.assertEqual([m['content'] for m in db.get_messages(self.chat_id)], ['Важливе питання'])

    def test_invalid_question_and_unknown_chat(self):
        for text in ('', '   ', 'x' * 8001):
            self.assertEqual(self.client.post(f'/chats/{self.chat_id}/ask', json={'text': text}).status_code, 422)
        self.assertEqual(db.get_messages(self.chat_id), [])
        self.assertEqual(self.client.post('/chats/9999/ask', json={'text': 'Питання'}).status_code, 404)


class Batch(list):
    def __getitem__(self, index):
        value = super().__getitem__(index)
        return Batch(value) if isinstance(index, slice) else value

    def tolist(self):
        return list(self)


class IngestTests(unittest.TestCase):
    def test_two_books_reindex_update_and_failure(self):
        import chromadb
        with tempfile.TemporaryDirectory() as directory:
            col = chromadb.EphemeralClient().create_collection('test-ingest', embedding_function=None)
            first, second = Path(directory) / 'one.pdf', Path(directory) / 'two.pdf'
            first.write_bytes(b'first')
            second.write_bytes(b'second')
            model = Mock()
            model.encode.side_effect = lambda texts, **kwargs: Batch([[1., 0., 0.] for _ in texts])
            reader = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: 'Агрономічний текст про культуру. ' * 40)])
            with patch('pypdf.PdfReader', return_value=reader):
                n1 = ingest(first, col, model)
                n2 = ingest(second, col, model)
                self.assertEqual(col.count(), n1 + n2)
                ingest(first, col, model)
                self.assertEqual(col.count(), n1 + n2)
                first.write_bytes(b'updated')
                reader.pages = [SimpleNamespace(extract_text=lambda: 'Новий текст про культуру. ' * 4)]
                ingest(first, col, model)
                self.assertEqual(col.count(), 1 + n2)
                model.encode.side_effect = RuntimeError('embedding failed')
                with self.assertRaises(RuntimeError):
                    ingest(first, col, model)
                self.assertEqual(col.count(), 1 + n2)
                reader.pages = [SimpleNamespace(extract_text=lambda: '')]
                with self.assertRaises(ValueError):
                    ingest(first, col, model)
                self.assertEqual(col.count(), 1 + n2)

    def test_chunk_overlap_validation(self):
        with self.assertRaises(ValueError):
            split('text', size=100, overlap=100)


class RagTests(unittest.TestCase):
    def test_empty_library_does_not_call_model(self):
        col = Mock()
        col.count.return_value = 0
        with patch.object(rag, 'resources', return_value=col), patch.object(rag, '_generate') as generate:
            result = rag.answer('Питання')
            self.assertIn('Бібліотека ще не проіндексована', result['answer'])
            generate.assert_not_called()

    def test_sources_and_result_limit(self):
        col, embedder = Mock(), Mock()
        col.count.return_value = 1
        col.get.return_value = {"ids": [], "documents": []}
        col.query.return_value = {'documents': [['Текст джерела про вирощування культури.']], 'metadatas': [[{'source': '/library/book.pdf', 'page': 2}]], 'distances': [[0.1]]}
        with patch.object(rag, 'resources', return_value=col), patch.object(rag, 'embedding_model', return_value=embedder), patch.object(rag, '_generate', return_value='{"answer":"Порада [S1]", "insufficient":false,"evidence":[{"source_id":"S1","quote":"Текст джерела про вирощування культури."}]}' ) as generate:
            result = rag.answer('Питання')
            self.assertEqual(result['pages'], [2])
            self.assertEqual(col.query.call_args.kwargs['n_results'], 1)
            self.assertIn('Документ: book.pdf; стор. 2', generate.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
