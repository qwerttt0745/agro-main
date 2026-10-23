import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from auth_client import TestClient
from app import rag, db, library, config
from app.main import app


class EvidenceTests(unittest.TestCase):
    chunks = [{'id': 'S1', 'source': 'a.pdf', 'page': 4, 'text': 'Дослівний фрагмент першої книги.'},
              {'id': 'S2', 'source': 'b.pdf', 'page': 4, 'text': 'Дослівний фрагмент другої книги.'}]

    def response(self, evidence, answer='Відповідь [S1]', insufficient=False):
        return json.dumps({'answer': answer, 'insufficient': insufficient, 'evidence': evidence})

    def test_valid_citation_and_same_page_different_books(self):
        raw = self.response([{'source_id': 'S1', 'quote': self.chunks[0]['text']},
                             {'source_id': 'S2', 'quote': self.chunks[1]['text']}], 'Відповідь [S1] [S2]')
        result = rag.validate_answer(raw, self.chunks, 'Питання')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual([s['document'] for s in result['sources']], ['a.pdf', 'b.pdf'])

    def test_fabricated_sources_quotes_and_missing_citation_rejected(self):
        variants = [self.response([{'source_id': 'S1', 'quote': self.chunks[1]['text']}]),
                    self.response([{'source_id': 'S9', 'quote': self.chunks[0]['text']}], 'Відповідь [S9]'),
                    self.response([{'source_id': 'S1', 'quote': 'Вигаданий фрагмент, якого тут немає.'}]),
                    self.response([], 'Непідтверджена порада'), 'not json']
        for raw in variants:
            with self.subTest(raw=raw):
                result = rag.validate_answer(raw, self.chunks, 'Питання')
                self.assertEqual(result['status'], 'invalid_evidence')
                self.assertEqual(result['sources'], [])

    def test_insufficient_does_not_show_model_invention(self):
        raw = self.response([], 'Ваш pH дорівнює 6', insufficient=True)
        result = rag.validate_answer(raw, self.chunks, 'Питання')
        self.assertEqual(result['status'], 'insufficient')
        self.assertNotIn('6', result['answer'])


class PersistenceTests(unittest.TestCase):
    def test_old_database_migration_and_sources_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, 'DB', Path(tmp) / 'chats.db'):
            with sqlite3.connect(db.DB) as conn:
                conn.executescript('CREATE TABLE chats(id INTEGER PRIMARY KEY, title TEXT, created_at TEXT); CREATE TABLE messages(id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT, pages TEXT, created_at TEXT); INSERT INTO chats VALUES(1, "old", "date"); INSERT INTO messages VALUES(1,1,"user","old question",NULL,"date");')
            from app import auth
            from scripts.migrate_users import migrate
            record={'username':'legacy','salt':'00'*16,'hash':auth.digest('legacy-password','00'*16),'version':'old-version'}
            (Path(tmp)/'auth_credentials.json').write_text(json.dumps(record))
            migrate(Path(tmp))
            db.init(); db.init()
            self.assertEqual(db.get_messages(1)[0]['content'], 'old question')
            self.assertEqual(db.get_messages(1)[0]['sources'], [])
            sources = [{'document': 'book.pdf', 'page': 4, 'quote': 'Цитата'}]
            db.add_message(1, 'assistant', 'Відповідь', [4], sources)
            self.assertEqual(db.get_messages(1)[1]['sources'], sources)

    def test_library_route_only_exposes_library_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'pdfs'; root.mkdir()
            (root / 'book.pdf').write_bytes(b'%PDF-test')
            secret = Path(tmp) / 'secret.pdf'; secret.write_bytes(b'private')
            (root / 'escape.pdf').symlink_to(secret)
            with patch.object(config, 'PDF_DIR', root), patch.object(db, 'DB', Path(tmp) / 'chats.db'):
                self.assertEqual(len(library.files()), 1)
                url = library.source_url('book.pdf', 4)
                with TestClient(app) as client:
                    self.assertEqual(client.get(url.split('#')[0]).content, b'%PDF-test')
                    self.assertEqual(client.get('/library/secret/pdf').status_code, 404)


class RetrievalTests(unittest.TestCase):
    def test_expands_only_same_document_page_and_deduplicates_hits(self):
        col, model = Mock(), Mock()
        col.count.return_value = 3
        col.query.return_value = {'documents': [['hit one', 'hit two']],
                                 'metadatas': [[{'source': 'a.pdf', 'page': 4}] * 2],
                                 'distances': [[0.1, 0.2]]}
        col.get.return_value = {'ids': ['doc-p4-1', 'doc-p4-0'],
                                'documents': ['Actual answer', 'Page heading']}
        with patch.object(rag, 'resources', return_value=col), patch.object(rag, 'embedding_model', return_value=model):
            result = rag.retrieve('question')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['text'], 'Page heading Actual answer')
        self.assertEqual(col.get.call_args.kwargs['where'],
                         {'$and': [{'source': 'a.pdf'}, {'page': 4}]})
