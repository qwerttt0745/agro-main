"""Authenticated transport for existing feature tests; auth itself is tested separately."""
from unittest.mock import patch
from fastapi.testclient import TestClient as BaseClient

class TestClient(BaseClient):
    def request(self,*args,**kwargs):
        kwargs['headers']={**(kwargs.get('headers') or {}),'X-Agro-Request':'1'}
        with patch('app.auth.authenticated',return_value=True):
            return super().request(*args,**kwargs)
