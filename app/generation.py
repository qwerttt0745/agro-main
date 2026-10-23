"""Owner-scoped cooperative cancellation for the single-process Compose deployment."""
import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass,field
import secrets
import threading
import time
from fastapi import HTTPException


class Cancelled(Exception):
    pass


@dataclass
class Job:
    owner:int
    chat_id:int
    request_id:str
    event:threading.Event=field(default_factory=threading.Event)
    lock:threading.Lock=field(default_factory=threading.Lock)
    completed:bool=False

    def cancel(self):
        with self.lock:
            if self.completed:return 'completed'
            self.event.set()
            return 'cancelled'

    def store(self,write):
        # Cancellation and saving an assistant row are serialized.
        with self.lock:
            if self.event.is_set():raise Cancelled()
            write()
            self.completed=True


_current=ContextVar('agro_generation',default=None)
_lock=threading.Lock()
_jobs={}
_recent=OrderedDict()


def check():
    job=_current.get()
    if job and job.event.is_set():raise Cancelled()


def _prune():
    now=time.monotonic()
    for key,(expiry,_,_) in list(_recent.items()):
        if expiry<=now:_recent.pop(key,None)
    while len(_recent)>1024:_recent.popitem(last=False)


def start(owner,chat_id,request_id=None):
    request_id=request_id or secrets.token_urlsafe(18)
    key=(owner,request_id)
    with _lock:
        _prune()
        if key in _jobs:raise HTTPException(409,'Цей запит уже обробляється.')
        previous=_recent.get(key)
        if previous and (previous[1]!=chat_id or previous[2]!='cancelled'):
            raise HTTPException(409,'Надішліть новий запит з іншим номером.')
        active=[job for job in _jobs.values() if job.owner==owner]
        if len(active)>=2:raise HTTPException(429,'Попередні запити ще завершуються. Зачекайте трохи.')
        if any(job.chat_id==chat_id and not job.event.is_set() for job in active):
            raise HTTPException(409,'У цьому чаті вже є активний запит.')
        if len(_jobs)>=16:raise HTTPException(429,'Зараз багато запитів. Спробуйте трохи пізніше.')
        job=Job(owner,chat_id,request_id)
        if previous:
            job.event.set();_recent.pop(key,None)
        _jobs[key]=job
    return job


def cancel(owner,chat_id,request_id):
    key=(owner,request_id)
    with _lock:
        _prune()
        job=_jobs.get(key)
        if job:
            if job.chat_id!=chat_id:raise HTTPException(404,'Запит не знайдено.')
            return job.cancel()
        previous=_recent.get(key)
        if previous:
            if previous[1]!=chat_id:raise HTTPException(404,'Запит не знайдено.')
            return previous[2]
        # Handles a Stop arriving before the ask body has finished uploading.
        _recent[key]=(time.monotonic()+60,chat_id,'cancelled')
        _prune()
        return 'cancelled'


def _finish(job):
    with _lock:
        _jobs.pop((job.owner,job.request_id),None)
        _recent[(job.owner,job.request_id)]=(time.monotonic()+60,job.chat_id,'cancelled' if job.event.is_set() else 'completed')
        _prune()


def cancelled_result(job):
    return {'status':'cancelled','answer':'Запит зупинено. Прийняте питання залишилося в історії.','pages':[],'sources':[],'request_id':job.request_id}


async def run(job,work):
    def worker():
        token=_current.set(job)
        try:
            return work()
        except Cancelled:
            return cancelled_result(job)
        finally:
            _current.reset(token)
            _finish(job)
    task=asyncio.create_task(asyncio.to_thread(worker))
    # Retrieve a late exception even when the HTTP response has already returned.
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        while not task.done():
            if job.event.is_set():return cancelled_result(job)
            await asyncio.wait({task},timeout=.05)
        result=task.result()
        return {**result,'request_id':job.request_id}
    except asyncio.CancelledError:
        job.cancel()
        raise


def store(write):
    job=_current.get()
    if job:job.store(write)
    else:write()
