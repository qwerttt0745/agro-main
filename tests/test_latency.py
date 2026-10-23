"""Latency controls must preserve conversation and strict citation validation."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock,patch
import httpx
import pytest
from app import rag,model_pool,performance

CHUNKS=[{'id':'S1','source':'book.pdf','page':1,'text':'Пшеницю вирощують на родючих ґрунтах.'}]
RAW=json.dumps({'answer':'Потрібні родючі ґрунти [S1].','insufficient':False,'evidence':[{'source_id':'S1','quote':CHUNKS[0]['text']}]})


def test_short_explicit_crop_question_does_not_need_rewrite():
    history=[{'role':'user','content':'Скільки росте пшениця?'},{'role':'assistant','content':'Відповідь.'}]
    with patch.object(rag,'_generate') as provider:
        assert rag.standalone_question('де садить пшеницю?',history)=='де садить пшеницю?'
        provider.assert_not_called()


def test_rewrite_failure_keeps_original_question_and_history():
    history=[{'role':'user','content':'Хочу посіяти пшеницю.'}]
    with patch.object(rag,'_generate',side_effect=rag.ServiceUnavailable('timeout')) as generate:
        assert rag.standalone_question('а де?',history)=='а де?'
        assert generate.call_args.kwargs['request_timeout']==5
        assert generate.call_args.kwargs['max_attempts']==1


def test_app_caps_main_and_repair_calls_and_validates_both():
    with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'retrieve',return_value=CHUNKS),patch.object(rag,'_generate',side_effect=['bad json',RAW]) as generate:
        assert rag.answer('Де сіяти пшеницю?')['status']=='answered'
        main,repair=generate.call_args_list
        assert main.kwargs['max_attempts']==2
        assert repair.kwargs['max_attempts']==1
        assert main.kwargs['deadline']==repair.kwargs['deadline']
        assert main.kwargs['request_timeout']==15
        assert repair.kwargs['request_timeout']==10
    with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'retrieve',return_value=CHUNKS),patch.object(rag,'_generate',side_effect=['bad json','bad json']):
        result=rag.answer('Де сіяти пшеницю?')
        assert result['status']=='invalid_evidence'
        assert result['sources']==[]


def test_provider_attempt_limit_and_thinking_config():
    client=Mock();client.models.generate_content.side_effect=httpx.ReadTimeout('secret-error')
    with patch.object(model_pool,'_state',{}),patch.object(rag,'llm_client',return_value=client),pytest.raises(rag.ServiceUnavailable):
        rag._generate('secret-question',max_attempts=2)
    assert client.models.generate_content.call_count==2
    assert client.models.generate_content.call_args_list[0].kwargs['config'].thinking_config.thinking_level=='LOW'
    assert client.models.generate_content.call_args_list[0].kwargs['config'].temperature is None


def test_elapsed_budget_stops_before_next_provider_call():
    now=[0.0]
    def timeout(**kwargs):
        now[0]=20.0
        raise httpx.ReadTimeout('secret-error')
    client=Mock();client.models.generate_content.side_effect=timeout
    with patch.object(model_pool,'_state',{}),patch.object(rag,'llm_client',return_value=client),patch.object(rag.time,'monotonic',side_effect=lambda:now[0]),pytest.raises(rag.ServiceUnavailable):
        rag._generate('q',deadline=15,max_attempts=2)
    assert client.models.generate_content.call_count==1
    assert client.models.generate_content.call_args.kwargs['config'].http_options.timeout==15000


def test_performance_logs_correlate_and_do_not_leak_exception(caplog):
    with caplog.at_level(logging.INFO,logger='uvicorn.error'):
        with pytest.raises(RuntimeError):
            with performance.request('text'):
                with performance.stage('provider',model='test'):
                    raise RuntimeError('secret-api-key secret-question')
    text=caplog.text
    assert 'agro_perf' in text and 'stage=provider' in text and 'stage=request' in text
    assert 'RuntimeError' in text
    assert 'secret-api-key' not in text and 'secret-question' not in text
    traces={record.getMessage().split('trace=')[1].split()[0] for record in caplog.records if 'agro_perf' in record.getMessage()}
    assert len(traces)==1
    assert performance._trace.get()=='-'
