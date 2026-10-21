"""Single household account; opaque revocable sessions, no plaintext passwords."""
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

CREDENTIALS = config.DATA / 'auth_credentials.json'
DATABASE = config.DATA / 'auth.db'
COOKIE = 'agro_session'
TTL = 14 * 86400
router = APIRouter()


def connect():
    connection=sqlite3.connect(DATABASE,timeout=10)
    connection.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, version TEXT, expires REAL)')
    connection.execute('CREATE TABLE IF NOT EXISTS attempts(ip TEXT, at REAL)')
    connection.execute('CREATE INDEX IF NOT EXISTS attempts_ip ON attempts(ip,at)')
    return connection


def credentials():
    try:return json.loads(CREDENTIALS.read_text())
    except (FileNotFoundError,ValueError):return None


def digest(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=131072,r=8,p=1,maxmem=256*1024*1024).hex()


def configure(username,password):
    if not username.strip() or len(username)>100 or not 12<=len(password)<=256:raise ValueError('Логін обов’язковий; пароль — щонайменше 12 символів.')
    salt=secrets.token_hex(16)
    record={'username':username.strip(),'salt':salt,'hash':digest(password,salt),'version':secrets.token_hex(16)}
    CREDENTIALS.parent.mkdir(parents=True,exist_ok=True)
    temp=CREDENTIALS.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(record,f)
    temp.replace(CREDENTIALS)


def authenticated(request):
    record=credentials();token=request.cookies.get(COOKIE,'')
    if not record or not token or len(token)>200:return False
    conn=connect()
    try:
        row=conn.execute('SELECT version,expires FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return bool(row and row[0]==record['version'] and row[1]>time.time())
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
    response=await call_next(request)
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
    record=credentials()
    if not record:raise HTTPException(503,'Власник ще не налаштував обліковий запис.')
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
        correct=hmac.compare_digest(digest(form.password,record['salt']),record['hash'])
        if not (correct and hmac.compare_digest(form.username.encode(),record['username'].encode())):
            raise HTTPException(401,'Невірний логін або пароль.')
        token=secrets.token_urlsafe(32)
        conn.execute('DELETE FROM sessions WHERE expires<? OR version!=?',(now,record['version']))
        conn.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),record['version'],now+TTL))
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
