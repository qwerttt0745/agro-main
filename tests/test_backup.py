import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from app import db, config
from scripts.backup import create_backup, verify

class BackupTests(unittest.TestCase):
    def test_snapshot_restores_messages_photos_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);database=root/'chats.db'
            with patch.object(db,'DB',database),patch.object(config,'CHATS_DB',database),patch.object(config,'DATA',root):
                db.init();chat=db.create_chat();db.add_message(chat,'user','Запит',photo=b'test-photo')
                (root/'farm_profile.json').write_text('{"crops":[]}')
                folder=create_backup();self.assertTrue(verify(folder))
                with sqlite3.connect(folder/'chats.db') as restored:
                    self.assertEqual(restored.execute('SELECT content FROM messages').fetchone()[0],'Запит')
                    self.assertEqual(restored.execute('SELECT data FROM photos').fetchone()[0],b'test-photo')
                self.assertFalse((folder/'.env').exists())
                (folder/'farm_profile.json').write_text('corrupted')
                with self.assertRaises(ValueError):verify(folder)
