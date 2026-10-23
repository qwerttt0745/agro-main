import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import auth,db,generation,rag
from app.main import app

FIRST='request-first-123456'
OTHER='request-other-123456'


@pytest.fixture(autouse=True)
def clean_recent_requests():
    with generation._lock:generation._recent.clear()


@pytest.fixture
def clients():
    for username in ('first','second'):auth.configure(username,'long-test-password',create=True)
    with TestClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'}) as first,TestClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'}) as second:
        for c,username in [(first,'first'),(second,'second')]:
            assert c.post('/auth/login',json={'username':username,'password':'long-test-password'}).status_code==200
        yield first,second


def test_stop_returns_before_blocked_provider_and_suppresses_late_answer(clients):
    first,_=clients
    chat=first.post('/chats').json()['id']
    entered=threading.Event();release=threading.Event()
    def slow(*args):
        entered.set();assert release.wait(5)
        return {'answer':'late answer','pages':[]}
    with ThreadPoolExecutor(1) as pool,patch.object(rag,'answer',side_effect=slow):
        future=pool.submit(first.post,f'/chats/{chat}/ask',json={'text':'question','request_id':FIRST})
        try:
            assert entered.wait(3)
            assert first.post(f'/chats/{chat}/cancel',json={'request_id':FIRST}).json()['status']=='cancelled'
            assert future.result(timeout=1).json()['status']=='cancelled'
            assert [m['role'] for m in first.get(f'/chats/{chat}').json()]==['user']
        finally:release.set()
    for _ in range(40):
        if (1,FIRST) not in generation._jobs:break
        time.sleep(.025)
    assert (1,FIRST) not in generation._jobs
    assert [m['role'] for m in first.get(f'/chats/{chat}').json()]==['user']
    with patch.object(rag,'answer',return_value={'answer':'new answer','pages':[]}):
        assert first.post(f'/chats/{chat}/retry',json={'request_id':OTHER}).status_code==200
    assert [m['content'] for m in first.get(f'/chats/{chat}').json()]==['question','new answer']


def test_stop_checks_owner_and_does_not_cancel_other_users_request(clients):
    first,second=clients
    chat=first.post('/chats').json()['id']
    entered=threading.Event();release=threading.Event()
    def slow(*args):
        entered.set();assert release.wait(5)
        return {'answer':'belongs to first','pages':[]}
    with ThreadPoolExecutor(1) as pool,patch.object(rag,'answer',side_effect=slow):
        future=pool.submit(first.post,f'/chats/{chat}/ask',json={'text':'question','request_id':FIRST})
        try:
            assert entered.wait(3)
            assert second.post(f'/chats/{chat}/cancel',json={'request_id':FIRST}).status_code==404
            release.set()
            assert future.result(timeout=2).json()['answer']=='belongs to first'
        finally:release.set()
    assert first.post(f'/chats/{chat}/cancel',json={'request_id':FIRST}).json()['status']=='completed'


def test_stop_before_upload_is_accepted_and_preserves_received_question(clients):
    first,_=clients
    chat=first.post('/chats').json()['id']
    assert first.post(f'/chats/{chat}/cancel',json={'request_id':FIRST}).json()['status']=='cancelled'
    with patch.object(rag,'answer') as generate:
        assert first.post(f'/chats/{chat}/ask',json={'text':'question','request_id':FIRST}).json()['status']=='cancelled'
        for _ in range(40):
            if (1,FIRST) not in generation._jobs:break
            time.sleep(.025)
        generate.assert_not_called()
    assert [m['content'] for m in first.get(f'/chats/{chat}').json()]==['question']


def test_provider_cancellation_prevents_model_switch(monkeypatch):
    import httpx
    from app import model_pool
    job=generation.start(999,123,FIRST)
    token=generation._current.set(job)
    client=Mock()
    def cancelled_provider(**kwargs):
        job.cancel()
        raise httpx.ReadTimeout('provider cancelled')
    client.models.generate_content.side_effect=cancelled_provider
    try:
        with patch.object(rag,'llm_client',return_value=client),patch.object(model_pool,'_state',{}),pytest.raises(generation.Cancelled):
            rag._generate('q')
        assert client.models.generate_content.call_count==1
    finally:
        generation._current.reset(token);generation._finish(job)


def test_cancelled_jobs_are_bounded_until_workers_finish():
    a=generation.start(998,1,FIRST);a.cancel()
    b=generation.start(998,1,OTHER);b.cancel()
    try:
        with pytest.raises(HTTPException) as error:
            generation.start(998,1,'request-third-123456')
        assert error.value.status_code==429
    finally:generation._finish(a);generation._finish(b)
