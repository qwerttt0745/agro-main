"""Correlated latency measurements; never log prompts, credentials or provider errors."""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import time
import uuid

_trace=ContextVar('agro_trace',default='-')
_log=logging.getLogger('uvicorn.error')


@contextmanager
def stage(name,**metrics):
    started=time.monotonic()
    status='ok'
    try:
        yield metrics
    except BaseException as exc:
        status='error'
        metrics['error_type']=type(exc).__name__
        raise
    finally:
        # Call sites supply only fixed labels, counts, model names and HTTP codes.
        fields=' '.join(f'{k}={v}' for k,v in metrics.items())
        _log.info('agro_perf trace=%s stage=%s seconds=%.3f status=%s %s',
                  _trace.get(),name,time.monotonic()-started,status,fields)


@contextmanager
def request(kind):
    token=_trace.set(uuid.uuid4().hex[:12])
    try:
        with stage('request',kind=kind):yield
    finally:_trace.reset(token)
