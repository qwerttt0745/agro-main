from types import SimpleNamespace
from unittest.mock import Mock,patch
import httpx
import pytest
from google.genai import errors
from app import rag,model_pool
from scripts.list_models import inventory,probe


def test_default_pool_has_seven_distinct_models():
    assert len(model_pool.MODELS)==len(set(model_pool.MODELS))==7
    assert 'gemini-2.5-flash-lite' in model_pool.MODELS
    assert 'gemini-3-flash-preview' in model_pool.MODELS


def test_explicit_extra_models_are_ordered_and_deduplicated(monkeypatch):
    monkeypatch.setenv('AGRO_EXTRA_MODELS','gemini-4-argon,gemini-3.8-flash,gemini-4-argon')
    assert model_pool.configured_models()==(*model_pool.MODELS,'gemini-4-argon')
    monkeypatch.setenv('AGRO_EXTRA_MODELS','not a model/key')
    with pytest.raises(ValueError):model_pool.configured_models()


def test_fast_quota_errors_can_reach_seventh_model_with_two_slow_attempts():
    client=Mock()
    client.models.generate_content.side_effect=[errors.ClientError(429,{'message':'quota'})]*6+[SimpleNamespace(text='ok')]
    with patch.object(model_pool,'_state',{}),patch.object(rag,'llm_client',return_value=client):
        assert rag._generate('q',max_attempts=2)=='ok'
    assert [c.kwargs['model'] for c in client.models.generate_content.call_args_list]==list(model_pool.MODELS)


def test_quick_missing_models_are_skipped_but_timeouts_are_bounded():
    client=Mock()
    client.models.generate_content.side_effect=[errors.ClientError(404,{'message':'missing'}),httpx.ReadTimeout('private'),httpx.ReadTimeout('private'),SimpleNamespace(text='should not reach')]
    with patch.object(model_pool,'_state',{}),patch.object(rag,'llm_client',return_value=client),pytest.raises(rag.ServiceUnavailable):
        rag._generate('q',max_attempts=2)
    assert client.models.generate_content.call_count==3


def test_slow_error_still_consumes_attempt_budget():
    clock=[0.]
    def fail(**kwargs):
        clock[0]+=5
        raise errors.ServerError(503,{'message':'busy'})
    client=Mock();client.models.generate_content.side_effect=fail
    with patch.object(model_pool,'_state',{}),patch.object(rag,'llm_client',return_value=client),patch.object(rag.time,'monotonic',side_effect=lambda:clock[0]),pytest.raises(rag.ServiceUnavailable):
        rag._generate('q',max_attempts=2,deadline=45)
    assert client.models.generate_content.call_count==2


def test_inventory_separates_listing_generation_and_configured_pool():
    client=Mock()
    client.models.list.return_value=[SimpleNamespace(name='models/gemini-3.8-flash',supported_actions=['generateContent']),
        SimpleNamespace(name='models/gemini-embedding-001',supported_actions=['embedContent']),
        SimpleNamespace(name='models/gemini-4-argon',supported_actions=['generateContent'])]
    data=inventory(client)
    assert data['listed_total']==3 and data['generate_content_total']==2
    assert data['configured_total']==7
    assert data['configured'][0]['listed']
    assert not data['configured'][-1]['listed']
    client.models.generate_content.assert_not_called()


def test_probe_reports_only_sanitized_errors_and_validates_json():
    client=Mock();client.models.generate_content.side_effect=[SimpleNamespace(text='{"description":"готово"}'),errors.ClientError(429,{'message':'secret-key private-url'})]
    rows=probe(client,['gemini-3.8-flash','gemini-2.5-flash-lite'])
    assert rows[0]['generation']=='ok'
    assert rows[1]['http_code']==429
    assert 'secret-key' not in str(rows) and 'private-url' not in str(rows)
