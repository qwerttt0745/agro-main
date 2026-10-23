"""Multiple accounts; opaque revocable sessions, no plaintext passwords."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from app import config
from app.identity import current_user

CREDENTIALS = config.DATA / 'auth_credentials.json'
DATABASE = config.DATA / 'auth.db'
COOKIE = 'agro_session'
TTL = 14 * 86400
router = APIRouter()


def connect():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection=sqlite3.connect(DATABASE,timeout=10)
    os.chmod(DATABASE,0o600)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.row_factory=sqlite3.Row
    connection.execute('CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,salt TEXT NOT NULL,created_at REAL NOT NULL,is_active INTEGER NOT NULL DEFAULT 1,version TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,version TEXT,expires REAL,user_id INTEGER NOT NULL REFERENCES users(id))')
    connection.execute('CREATE TABLE IF NOT EXISTS attempts(ip TEXT,at REAL)')
    connection.execute('CREATE INDEX IF NOT EXISTS attempts_ip ON attempts(ip,at)')
    return connection


def credentials():
    try:return json.loads(CREDENTIALS.read_text())
    except (FileNotFoundError,ValueError):return None


def digest(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=131072,r=8,p=1,maxmem=256*1024*1024).hex()


def configure(username,password,*,create=False):
    username=username.strip()
    if not username or len(username)>100 or not 12<=len(password)<=256:
        raise ValueError('Логін обов’язковий; пароль — 12–256 символів.')
    check_ready()
    conn=connect()
    try:
        if CREDENTIALS.exists() and not conn.execute('SELECT 1 FROM users').fetchone():
            raise ValueError('Спочатку виконайте резервне копіювання та міграцію.')
        salt=secrets.token_hex(16)
        hashed=digest(password,salt)
        with conn:
            if create:
                conn.execute('INSERT INTO users(username,password_hash,salt,created_at,version) VALUES (?,?,?,?,?)',
                             (username,hashed,salt,time.time(),secrets.token_hex(16)))
            else:
                row=conn.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
                if not row:raise ValueError('Користувача не знайдено. Використайте scripts.create_user.')
                conn.execute('UPDATE users SET password_hash=?,salt=?,version=? WHERE id=?',(hashed,salt,secrets.token_hex(16),row['id']))
                conn.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
    finally:conn.close()


def authenticated(request):
    token=request.cookies.get(COOKIE,'')
    if not token or len(token)>200:return False
    conn=connect()
    try:
        row=conn.execute('SELECT u.id FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.version=u.version AND s.expires>? AND u.is_active=1',
                         (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if row:request.state.user_id=row['id']
        return bool(row)
    finally:conn.close()


async def protect(request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        expected=os.getenv('AGRO_PUBLIC_ORIGIN',str(request.base_url).rstrip('/'))
        if request.headers.get('x-agro-request')!='1' or (origin and origin!=expected):
            return JSONResponse({'detail':'Запит з іншого сайту відхилено.'},403)
    public=request.url.path in ('/login','/auth/login')
    if not public and not authenticated(request):
        if request.method=='GET' and (request.url.path in ('/','/farm') or 'text/html' in request.headers.get('accept','')):
            return RedirectResponse('/login',303)
        return JSONResponse({'detail':'Потрібно увійти.'},401)
    identity_token=current_user.set(getattr(request.state,'user_id',None))
    try:
        response=await call_next(request)
    finally:
        current_user.reset(identity_token)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    return response


class Login(BaseModel):
    username:str=Field(max_length=100)
    password:str=Field(max_length=256)


@router.get('/login')
def login_page():return FileResponse(config.ROOT/'static/login.html')


@router.post('/auth/login')
def login(request:Request,form:Login):

    secure=os.getenv('AGRO_COOKIE_SECURE','true').lower()!='false'
    if not secure and request.url.hostname not in ('127.0.0.1','localhost','testserver'):
        raise HTTPException(503,'Для зовнішнього доступу потрібен HTTPS.')
    ip=request.client.host if request.client else 'unknown'
    conn=connect();now=time.time()
    try:
        # Serialize attempt reservation, so parallel attempts cannot bypass the limit.
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM attempts WHERE at<?',(now-900,))
        if conn.execute('SELECT count(*) FROM attempts WHERE ip=?',(ip,)).fetchone()[0]>=5:
            conn.rollback();raise HTTPException(429,'Забагато спроб. Спробуйте через 15 хвилин.')
        conn.execute('INSERT INTO attempts VALUES (?,?)',(ip,now));conn.commit()
        record=conn.execute('SELECT * FROM users WHERE username=?',(form.username,)).fetchone()
        computed=digest(form.password,record['salt'] if record else '00'*16)
        correct=hmac.compare_digest(computed,record['password_hash'] if record else '00'*64)
        if not (record and correct and record['is_active']):
            raise HTTPException(401,'Невірний логін або пароль.')
        token=secrets.token_urlsafe(32)
        conn.execute('DELETE FROM sessions WHERE expires<?',(now,))
        conn.execute('INSERT INTO sessions(token,version,expires,user_id) VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),record['version'],now+TTL,record['id']))
        conn.execute('DELETE FROM attempts WHERE ip=?',(ip,));conn.commit()
    finally:conn.close()
    response=JSONResponse({'ok':True})
    response.set_cookie(COOKIE,token,max_age=TTL,httponly=True,secure=secure,samesite='strict',path='/')
    return response


@router.post('/auth/logout')
def logout(request:Request):
    conn=connect()
    try:
        conn.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(request.cookies.get(COOKIE,'').encode()).hexdigest(),));conn.commit()
    finally:conn.close()
    response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/');return response


def check_ready():
    if CREDENTIALS.exists():
        if not DATABASE.exists():raise RuntimeError('Run scripts.migrate_users --offline first.')
        with sqlite3.connect(f'file:{DATABASE}?mode=ro',uri=True) as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone() or not c.execute('SELECT 1 FROM users').fetchone():
                raise RuntimeError('Run scripts.migrate_users --offline first.')
    if DATABASE.exists():
        with sqlite3.connect(f'file:{DATABASE}?mode=ro',uri=True) as c:
            columns={r[1] for r in c.execute('PRAGMA table_info(sessions)')}
            if columns and 'user_id' not in columns:raise RuntimeError('Run scripts.migrate_users --offline first.')
