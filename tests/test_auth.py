import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import auth, db
from app.main import app

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        for obj,key,value in [(auth,'CREDENTIALS',root/'credentials.json'),(auth,'DATABASE',root/'auth.db'),(db,'DB',root/'chats.db')]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'AGRO_COOKIE_SECURE':'true','AGRO_PUBLIC_ORIGIN':'https://testserver'});p.start();self.addCleanup(p.stop)
        auth.configure('tato','long-test-password',create=True)
        self.client=TestClient(app,base_url='https://testserver',headers={'X-Agro-Request':'1'})
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)

    def login(self,password='long-test-password'):
        return self.client.post('/auth/login',json={'username':'tato','password':password})

    def test_private_routes_and_login_cookie_logout(self):
        for path in ['/chats','/api/farm','/library/unknown/pdf','/chats/1/photos/test','/static/index.html','/openapi.json']:
            self.assertEqual(self.client.get(path,follow_redirects=False).status_code,401)
        self.assertEqual(self.client.get('/',follow_redirects=False).status_code,303)
        r=self.login();self.assertEqual(r.status_code,200)
        cookie=r.headers['set-cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=strict',cookie)
        old=self.client.cookies.get(auth.COOKIE)
        self.assertEqual(self.client.get('/chats').status_code,200)
        self.assertEqual(self.client.post('/auth/logout').status_code,200)
        self.client.cookies.set(auth.COOKIE,old)
        self.assertEqual(self.client.get('/chats').status_code,401)

    def test_csrf_and_bruteforce(self):
        r=self.client.post('/auth/login',json={'username':'tato','password':'long-test-password'},headers={'Origin':'https://evil.test'})
        self.assertEqual(r.status_code,403)
        for _ in range(5):self.assertEqual(self.login('incorrect').status_code,401)
        self.assertEqual(self.login().status_code,429)

    def test_password_change_revokes_sessions_and_no_plaintext(self):
        self.login();auth.configure('tato','new-long-password')
        self.assertEqual(self.client.get('/chats').status_code,401)
        self.assertNotIn(b'new-long-password',auth.DATABASE.read_bytes())

    def test_expired_session_and_missing_configuration_fail_closed(self):
        self.login()
        conn=auth.connect();conn.execute('UPDATE sessions SET expires=0');conn.commit();conn.close()
        self.assertEqual(self.client.get('/chats').status_code,401)
        conn=auth.connect();conn.execute("UPDATE users SET is_active=0");conn.commit();conn.close()
        self.assertEqual(self.login().status_code,401)
        self.assertEqual(self.client.get('/api/farm').status_code,401)
