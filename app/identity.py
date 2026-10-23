"""Request-local identity, propagated into AnyIO/asyncio worker threads."""
from contextvars import ContextVar
from fastapi import HTTPException

current_user = ContextVar('agro_user', default=None)


def user_id():
    value = current_user.get()
    if value is None:
        raise HTTPException(401, 'Потрібно увійти.')
    return value
