"""Security integration tests: real scrypt, cookies, middleware and SQLite."""
import asyncio
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import auth, config, db, farm, fields, live, rag
from app.identity import current_user
from app.main import app
from scripts.migrate_users import migrate, restore, verify

PASSWORD='existing-password-123'


def legacy(root):
    # Exact old schema, IDs, binary data and opaque session token.
    (root/'chats.db').unlink(missing_ok=True)
    record={'username':'owner','salt':'12'*16,'hash':auth.digest(PASSWORD,'12'*16),'version':'keep-version'}
    (root/'auth_credentials.json').write_text(json.dumps(record))
    (root/'farm_profile.json').write_text(json.dumps({'crops':['private-crop'],'latitude':49,'longitude':29}))
    (root/'site').mkdir()
    (root/'site/summary.json').write_text('{"private-climate":true}')
    with sqlite3.connect(root/'auth.db') as c:
        c.executescript('CREATE TABLE sessions(token TEXT PRIMARY KEY,version TEXT,expires REAL);CREATE TABLE attempts(ip TEXT,at REAL);')
        c.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(b'old-token').hexdigest(),'keep-version',time.time()+3600))
    with sqlite3.connect(root/'chats.db') as c:
        c.executescript('''CREATE TABLE chats(id INTEGER PRIMARY KEY,title TEXT,created_at TEXT);
        CREATE TABLE messages(id INTEGER PRIMARY KEY,chat_id INTEGER REFERENCES chats(id),role TEXT,content TEXT,pages TEXT,created_at TEXT,photo_id TEXT,sources TEXT);
        CREATE TABLE photos(id TEXT PRIMARY KEY,chat_id INTEGER REFERENCES chats(id),data BLOB);
        CREATE TABLE farm_fields(id INTEGER PRIMARY KEY,payload TEXT,updated_at TEXT);
        CREATE TABLE product_labels(id INTEGER PRIMARY KEY,name TEXT,note TEXT,image BLOB,created_at TEXT);
        INSERT INTO chats VALUES(7,'private-chat','date');
        INSERT INTO messages VALUES(8,7,'user','private-question','[]','date','photo','[]');
        INSERT INTO photos VALUES('photo',7,X'010203');
        INSERT INTO farm_fields VALUES(9,'{"name":"private-field"}','date');
        INSERT INTO product_labels VALUES(10,'private-label','note',X'040506','date');''')
    return record


def client(username=None):
    c=TestClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'})
    if username:
        assert c.post('/auth/login',json={'username':username,'password':PASSWORD}).status_code==200
    return c


def migrated(root):
    legacy(root)
    folder=migrate(root)
    db.init()
    auth.configure('second',PASSWORD,create=True)
    return folder


def test_migration_preserves_everything_and_restart(tmp_path):
    original=legacy(tmp_path)
    before=(tmp_path/'auth_credentials.json').read_bytes()
    with pytest.raises(RuntimeError):auth.check_ready()
    with pytest.raises(RuntimeError):db.init()
    folder=migrate(tmp_path)
    assert verify(folder)
    assert (tmp_path/'auth_credentials.json').read_bytes()==before
    with auth.connect() as c:
        user=c.execute('SELECT * FROM users').fetchone()
        assert (user['password_hash'],user['salt'],user['version'])==(original['hash'],original['salt'],original['version'])
        assert c.execute('SELECT user_id FROM sessions').fetchone()[0]==user['id']
    with client() as c:
        c.cookies.set(auth.COOKIE,'old-token')
        assert c.get('/chats/7').json()[0]['content']=='private-question'
        assert c.get('/chats/7/photos/photo').content==b'\x01\x02\x03'
        assert c.get('/api/fields').json()[0]['id']==9
        assert c.get('/api/labels/10/image').content==b'\x04\x05\x06'
        assert c.get('/api/farm').json()['profile']['crops']==['private-crop']
    # New app lifespan and connections, with persisted session token.
    with client() as c:
        c.cookies.set(auth.COOKIE,'old-token')
        assert c.get('/chats').json()[0]['id']==7
    with pytest.raises(ValueError):migrate(tmp_path)


def test_cross_user_access_and_independent_sessions(tmp_path):
    migrated(tmp_path)
    with client('owner') as owner,client('second') as second:
        assert second.get('/chats').json()==[]
        assert second.get('/api/fields').json()==[]
        assert second.get('/api/labels').json()==[]
        assert second.get('/api/farm').json()['profile']=={}
        assert second.get('/api/farm').json()['climate']=={}
        assert second.get('/api/weather').status_code==503
        for path in ('/chats/7','/chats/7/photos/photo','/api/labels/10/image'):
            assert second.get(path).status_code==404
        with patch.object(rag,'answer') as answer:
            assert second.post('/chats/7/ask',json={'text':'steal'}).status_code==404
            assert second.post('/chats/7/retry').status_code==404
            answer.assert_not_called()
        assert second.put('/api/fields/9',json={'name':'stolen'}).status_code==404
        assert second.delete('/api/labels/10').status_code==404
        own=second.post('/chats').json()['id']
        assert owner.get(f'/chats/{own}').status_code==404
        field=second.post('/api/fields',json={'name':'second-field'}).json()['id']
        assert owner.put(f'/api/fields/{field}',json={'name':'stolen'}).status_code==404
        auth.configure('owner','replacement-password')
        assert owner.get('/chats').status_code==401
        assert second.get('/chats').status_code==200
        assert second.post('/auth/logout').status_code==200
        assert second.get('/chats').status_code==401


def test_context_isolation_concurrent_requests_and_websocket(tmp_path):
    migrated(tmp_path)
    with client('owner') as owner,client('second') as second:
        ids=[owner.post('/chats').json()['id'],second.post('/chats').json()['id']]
        def answer(*args):
            return {'answer':json.dumps({'profile':farm.profile(),'fields':fields.records()}),'pages':[]}
        def ask(pair):
            c,chat=pair
            return c.post(f'/chats/{chat}/ask',json={'text':'question'}).json()
        with patch.object(rag,'answer',side_effect=answer),ThreadPoolExecutor(2) as pool:
            results=list(pool.map(ask,zip([owner,second],ids)))
        assert 'private-crop' in results[0]['answer']
        assert 'private-field' in results[0]['answer']
        assert 'private-' not in results[1]['answer']
        # Same identity mechanism used by the actual websocket relay.
        ws=SimpleNamespace(cookies={auth.COOKIE:second.cookies.get(auth.COOKIE)},state=SimpleNamespace(),headers={'origin':'https://testserver'},base_url='wss://testserver/')
        assert live.allowed(ws)
        token=current_user.set(ws.state.user_id)
        try:
            assert asyncio.run(asyncio.to_thread(farm.profile))=={}
            with pytest.raises(HTTPException):db.add_message(7,'user','forbidden')
        finally:current_user.reset(token)
        assert current_user.get() is None


def test_backup_tamper_and_rollback(tmp_path):
    folder=migrated(tmp_path)
    safety=restore(tmp_path,folder)
    assert verify(safety)
    with sqlite3.connect(tmp_path/'auth.db') as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
    with sqlite3.connect(tmp_path/'chats.db') as c:
        assert c.execute('SELECT content FROM messages').fetchone()[0]=='private-question'
    with pytest.raises(RuntimeError):auth.check_ready()
    (folder/'auth_credentials.json').write_text('{}')
    with pytest.raises(ValueError):restore(tmp_path,folder)


def test_duplicate_user_and_no_implicit_migration(tmp_path):
    legacy(tmp_path)
    before=(tmp_path/'auth.db').read_bytes()
    with pytest.raises(RuntimeError):auth.configure('owner',PASSWORD,create=True)
    assert (tmp_path/'auth.db').read_bytes()==before
    migrate(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):auth.configure('owner',PASSWORD,create=True)
    assert client('owner').get('/chats').status_code==200


def test_corruption_aborts_before_migration(tmp_path):
    legacy(tmp_path)
    (tmp_path/'chats.db').write_bytes(b'broken database')
    with pytest.raises(sqlite3.DatabaseError):migrate(tmp_path)
    with sqlite3.connect(tmp_path/'auth.db') as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()


def test_websocket_uses_authenticated_users_profile(tmp_path):
    from unittest.mock import AsyncMock
    from starlette.websockets import WebSocketDisconnect
    migrated(tmp_path)
    instructions=[]
    class Session:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def receive(self):
            await asyncio.sleep(60)
            if False:yield None
    def connect(**kwargs):
        instructions.append(str(kwargs['config'].system_instruction))
        return Session()
    provider=SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect),aclose=AsyncMock()))
    for name in ('owner','second'):
        with client(name) as web,patch.object(live.genai,'Client',return_value=provider):
            with web.websocket_connect('wss://testserver/api/live',headers={'origin':'https://testserver'}) as ws:
                assert ws.receive_json()['type']=='ready'
                ws.send_json({'type':'stop'})
                with pytest.raises(WebSocketDisconnect):ws.receive_json()
    assert 'private-crop' in instructions[0]
    assert 'private-crop' not in instructions[1]
    assert not live._active


def test_cli_password_is_interactive_and_duplicate_safe(tmp_path,monkeypatch):
    import sys
    from scripts.create_user import main
    migrated(tmp_path)
    monkeypatch.setattr(sys,'argv',['create_user','--username','third'])
    with patch('scripts.create_user.getpass.getpass',side_effect=[PASSWORD,PASSWORD]):main()
    with client('third') as third:assert third.get('/chats').json()==[]
    with patch('scripts.create_user.getpass.getpass',side_effect=[PASSWORD,PASSWORD]),pytest.raises(SystemExit):main()
    with patch('scripts.create_user.getpass.getpass',side_effect=[PASSWORD,'mismatch']),pytest.raises(SystemExit):main()


def test_migration_transaction_rolls_back_on_write_failure(tmp_path,monkeypatch):
    legacy(tmp_path)
    original_connect=sqlite3.connect
    class FailConnection(sqlite3.Connection):
        def execute(self,sql,*args,**kwargs):
            if sql.startswith('INSERT INTO private.user_documents'):raise RuntimeError('Injected write failure')
            return super().execute(sql,*args,**kwargs)
    def connection(*args,**kwargs):
        kwargs['factory']=FailConnection
        return original_connect(*args,**kwargs)
    with patch('scripts.migrate_users.sqlite3.connect',side_effect=connection):
        with pytest.raises(RuntimeError):migrate(tmp_path)
    with original_connect(tmp_path/'auth.db') as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
    with original_connect(tmp_path/'chats.db') as c:
        assert 'user_id' not in {r[1] for r in c.execute('PRAGMA table_info(chats)')}
        assert c.execute('SELECT count(*) FROM messages').fetchone()[0]==1
    assert verify(next((tmp_path/'backups').iterdir()))


def test_data_and_sessions_survive_real_process_restart(tmp_path):
    import os
    import socket
    import subprocess
    import sys
    import httpx
    from contextlib import contextmanager
    migrated(tmp_path)
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env={**os.environ,'AGRO_DATA_DIR':str(tmp_path),'AGRO_COOKIE_SECURE':'false','AGRO_PUBLIC_ORIGIN':f'http://127.0.0.1:{port}'}
    @contextmanager
    def server():
        p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if p.poll() is not None:pytest.fail('Local server exited')
                try:
                    if httpx.get(f'http://127.0.0.1:{port}/login',timeout=1).status_code==200:break
                except httpx.TransportError:pass
                time.sleep(.1)
            else:pytest.fail('Local server did not start')
            yield
        finally:
            p.terminate()
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait()
    with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'X-Agro-Request':'1'}) as web:
        with server():
            assert web.post('/auth/login',json={'username':'owner','password':PASSWORD}).status_code==200
            new_id=web.post('/chats').json()['id']
        with server():
            assert web.get(f'/chats/{new_id}').status_code==200
            assert web.get('/chats/7').json()[0]['content']=='private-question'
            assert web.get('/chats/7/photos/photo').content==b'\x01\x02\x03'
            assert web.get('/api/farm').json()['profile']['crops']==['private-crop']
