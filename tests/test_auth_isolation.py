"""An error creating one account must not change another account's credentials."""
import sqlite3
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app import auth
from app.main import app

PASSWORD='long-test-password'


def account_rows():
    with auth.connect() as c:return [tuple(row) for row in c.execute('SELECT * FROM users ORDER BY id')]


def test_account_creation_and_duplicate_leave_existing_accounts_unchanged():
    auth.configure('tato',PASSWORD,create=True)
    auth.configure('oleksii',PASSWORD,create=True)
    before=account_rows()
    auth.configure('mama',PASSWORD,create=True)
    assert account_rows()[:2]==before
    with pytest.raises(sqlite3.IntegrityError):auth.configure('tato','another-password',create=True)
    assert account_rows()[:2]==before


def test_five_bad_logins_block_only_that_account_at_same_ip():
    auth.configure('tato',PASSWORD,create=True)
    auth.configure('oleksii',PASSWORD,create=True)
    with TestClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'}) as client:
        for _ in range(5):assert client.post('/auth/login',json={'username':'tato','password':'incorrect'}).status_code==401
        assert client.post('/auth/login',json={'username':'tato','password':PASSWORD}).status_code==429
        assert client.post('/auth/login',json={'username':'oleksii','password':PASSWORD}).status_code==200
        assert client.get('/chats').status_code==200
        # The other account's successful login must not clear tato's limit.
        assert client.post('/auth/login',json={'username':'tato','password':PASSWORD}).status_code==429


def test_old_shared_ip_counter_does_not_lock_everyone_after_upgrade():
    auth.configure('tato',PASSWORD,create=True)
    with auth.connect() as c:
        c.executemany('INSERT INTO attempts VALUES (?,?)',[('testclient',time.time())]*5)
    with TestClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'}) as client:
        assert client.post('/auth/login',json={'username':'tato','password':PASSWORD}).status_code==200


def test_broad_ip_limit_still_blocks_rotating_usernames():
    auth.configure('tato',PASSWORD,create=True)
    with auth.connect() as c:
        c.executemany('INSERT INTO login_attempts VALUES (?,?,?)',[('testclient',str(i),time.time()) for i in range(100)])
    with TestClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'}) as client:
        assert client.post('/auth/login',json={'username':'tato','password':PASSWORD}).status_code==429
