"""Authenticated transport for existing feature tests; auth itself is tested separately."""
from unittest.mock import patch
from fastapi.testclient import TestClient as BaseClient

def authenticated(request):
    request.state.user_id=1
    return True

class TestClient(BaseClient):
    def request(self,*args,**kwargs):
        kwargs['headers']={**(kwargs.get('headers') or {}),'X-Agro-Request':'1'}
        with patch('app.auth.authenticated',side_effect=authenticated):
            return super().request(*args,**kwargs)
