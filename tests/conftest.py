"""Isolate feature tests from real data; security tests use real login middleware."""
import pytest
from app import config, db, auth
from app.identity import current_user


@pytest.fixture(autouse=True)
def isolated_data(tmp_path,monkeypatch,request):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(config,'CHATS_DB',tmp_path/'chats.db')
    monkeypatch.setattr(db,'DB',tmp_path/'chats.db')
    monkeypatch.setattr(auth,'DATABASE',tmp_path/'auth.db')
    monkeypatch.setattr(auth,'CREDENTIALS',tmp_path/'auth_credentials.json')
    db.init()
    token=current_user.set(None if request.node.path.name=='test_multiuser.py' else 1)
    yield
    current_user.reset(token)
