"""Explicit offline migration. The verified snapshot is created BEFORE any DB write."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from app import config

TABLES=('chats','messages','photos','farm_fields','product_labels')


def check_database(path):
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite integrity check failed')


def snapshot(data):
    folder=data/'backups'/datetime.now(timezone.utc).strftime('users-%Y%m%dT%H%M%S-%fZ')
    folder.mkdir(parents=True,mode=0o700)
    os.chmod(folder,0o700)
    paths=[]
    for path in data.rglob('*'):
        relative=path.relative_to(data)
        if relative.parts[0] in ('backups','chroma') or not path.is_file():continue
        if path.is_symlink():raise ValueError('Symlinks are not supported in migration data')
        if path.suffix in ('.db','.sqlite','.sqlite3','.json'):paths.append(path)
    for path in paths:
        target=folder/path.relative_to(data)
        target.parent.mkdir(parents=True,exist_ok=True)
        if path.suffix!='.json':
            check_database(path)
            with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as src, sqlite3.connect(target) as dst:src.backup(dst)
        else:
            json.loads(path.read_text())
            shutil.copyfile(path,target)
        os.chmod(target,0o600)
    manifest={'files':{str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()},
              'absent':[name for name in ('auth.db','chats.db') if not (data/name).exists()]}
    (folder/'migration-manifest.json').write_text(json.dumps(manifest,indent=2))
    verify(folder)
    return folder


def verify(folder):
    folder=Path(folder).resolve()
    manifest=json.loads((folder/'migration-manifest.json').read_text())
    for name,digest in manifest['files'].items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Snapshot checksum mismatch')
        if path.suffix in ('.db','.sqlite','.sqlite3'):check_database(path)
        elif path.suffix=='.json':json.loads(path.read_text())
    return manifest


def restore(data,folder):
    data=Path(data).resolve();folder=Path(folder).resolve()
    manifest=verify(folder)
    # Also retain a verified snapshot of the state being rolled back.
    safety=snapshot(data)
    for name in list(manifest['files'])+manifest['absent']:
        target=(data/name).resolve()
        if not target.is_relative_to(data):raise ValueError('Invalid restore path')
        if target.suffix in ('.db','.sqlite','.sqlite3'):
            for suffix in ('-wal','-shm','-journal'):Path(str(target)+suffix).unlink(missing_ok=True)
        if name in manifest['files']:
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.restore')
            shutil.copyfile(folder/name,temporary);os.chmod(temporary,0o600);temporary.replace(target)
        else:target.unlink(missing_ok=True)
    return safety


def migrate(data):
    data=Path(data).resolve()
    legacy=data/'auth_credentials.json'
    # Read-only preflight; no connect() helper may initialize schemas here.
    record=json.loads(legacy.read_text())
    for key in ('username','hash','salt','version'):
        if not isinstance(record.get(key),str) or not record[key]:raise ValueError('Invalid legacy credentials')
    if len(bytes.fromhex(record['salt']))!=16 or len(bytes.fromhex(record['hash']))!=64:
        raise ValueError('Invalid legacy scrypt record')
    if (data/'auth.db').exists():
        with sqlite3.connect(f'file:{data / "auth.db"}?mode=ro',uri=True) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone() and c.execute('SELECT 1 FROM users').fetchone():
                raise ValueError('Migration already completed; existing users will not be changed')
    folder=snapshot(data)
    c=sqlite3.connect(data/'auth.db')
    os.chmod(data/'auth.db',0o600)
    try:
        c.execute('ATTACH DATABASE ? AS private',(str(data/'chats.db'),))
        os.chmod(data/'chats.db',0o600)
        # Attached SQLite DBs commit atomically using rollback journals (offline only).
        c.execute('PRAGMA main.journal_mode=DELETE');c.execute('PRAGMA private.journal_mode=DELETE')
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,salt TEXT NOT NULL,created_at REAL NOT NULL,is_active INTEGER NOT NULL DEFAULT 1,version TEXT NOT NULL)')
        uid=c.execute('INSERT INTO users(username,password_hash,salt,created_at,version) VALUES (?,?,?,?,?)',
                      (record['username'],record['hash'],record['salt'],time.time(),record['version'])).lastrowid
        c.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,version TEXT,expires REAL)')
        if 'user_id' not in {r[1] for r in c.execute('PRAGMA table_info(sessions)')}:
            c.execute('ALTER TABLE sessions ADD COLUMN user_id INTEGER REFERENCES users(id)')
        c.execute('UPDATE sessions SET user_id=?',(uid,))
        for table in TABLES:
            if not c.execute("SELECT 1 FROM private.sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
            if 'user_id' not in {r[1] for r in c.execute(f'PRAGMA private.table_info({table})')}:
                c.execute(f'ALTER TABLE private.{table} ADD COLUMN user_id INTEGER')
            c.execute(f'UPDATE private.{table} SET user_id=?',(uid,))
            c.execute(f'CREATE INDEX IF NOT EXISTS private.{table}_owner ON {table}(user_id)')
        c.execute('CREATE TABLE private.user_documents(user_id INTEGER NOT NULL,name TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(user_id,name))')
        for name in ('farm_profile.json','site/summary.json'):
            path=data/name
            if path.exists():c.execute('INSERT INTO private.user_documents VALUES (?,?,?)',(uid,name,path.read_text()))
        for schema in ('main','private'):
            if c.execute(f'PRAGMA {schema}.integrity_check').fetchone()[0]!='ok' or c.execute(f'PRAGMA {schema}.foreign_key_check').fetchone():
                raise ValueError('Migration integrity check failed')
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:c.close()
    return folder


def main():
    parser=argparse.ArgumentParser(description='Офлайн міграція/відкат. Спочатку зупиніть усі процеси Agro AI.')
    parser.add_argument('--data',type=Path,default=config.DATA)
    parser.add_argument('--offline',action='store_true',help='Підтверджую, що застосунок та інші writers зупинено')
    parser.add_argument('--restore',type=Path)
    parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:verify(args.verify);print('Копію перевірено');return
    if not args.offline:parser.error('Потрібно зупинити застосунок і вказати --offline')
    result=restore(args.data,args.restore) if args.restore else migrate(args.data)
    print(f'Операцію завершено. Перевірена резервна копія: {result}')


if __name__=='__main__':main()
