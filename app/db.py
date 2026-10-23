from app import config
from app.identity import user_id
from fastapi import HTTPException
import os
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

DB = config.CHATS_DB


@contextmanager
def _conn():
    c = sqlite3.connect(DB)
    os.chmod(DB,0o600)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        with c:
            yield c
    finally:
        c.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def init():
    if DB.exists():
        with sqlite3.connect(f'file:{DB}?mode=ro',uri=True) as old:
            for table in ('chats','messages','photos','farm_fields','product_labels'):
                columns={r[1] for r in old.execute(f'PRAGMA table_info({table})')}
                if columns and 'user_id' not in columns:
                    raise RuntimeError('Run scripts.migrate_users --offline after stopping the application.')
    DB.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL REFERENCES chats(id),
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            pages TEXT,
            created_at TEXT
        );
        """)
        c.execute("""CREATE TABLE IF NOT EXISTS photos (
            id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id),
            data BLOB NOT NULL,user_id INTEGER NOT NULL)""")
        c.execute('CREATE TABLE IF NOT EXISTS user_documents(user_id INTEGER NOT NULL,name TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(user_id,name))')
        columns = {row["name"] for row in c.execute("PRAGMA table_info(messages)")}
        if "photo_id" not in columns:
            c.execute("ALTER TABLE messages ADD COLUMN photo_id TEXT")
        if "sources" not in columns:
            c.execute("ALTER TABLE messages ADD COLUMN sources TEXT")


def create_chat():
    with _conn() as c:
        return c.execute("INSERT INTO chats (created_at,user_id) VALUES (?,?)", (_now(),user_id())).lastrowid


def chat_exists(chat_id):
    with _conn() as c:
        return c.execute("SELECT 1 FROM chats WHERE id = ? AND user_id=?", (chat_id,user_id())).fetchone() is not None


def list_chats():
    with _conn() as c:
        rows = c.execute(
            "SELECT id, COALESCE(title, 'Новий чат') AS title, created_at FROM chats WHERE user_id=? ORDER BY id DESC", (user_id(),)
        ).fetchall()
        return [dict(r) for r in rows]


def get_messages(chat_id):
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, pages, sources, photo_id, created_at FROM messages WHERE chat_id = ? AND user_id=? ORDER BY id",
            (chat_id,user_id()),
        ).fetchall()
        return [
            {"role": r["role"], "content": r["content"],
             "photo_url": f"/chats/{chat_id}/photos/{r['photo_id']}" if r["photo_id"] else None,
             "pages": json.loads(r["pages"] or "[]"), "sources": json.loads(r["sources"] or "[]"), "created_at": r["created_at"]}
            for r in rows
        ]


def add_message(chat_id, role, content, pages=None, sources=None, photo=None):
    with _conn() as c:
        if not c.execute('SELECT 1 FROM chats WHERE id=? AND user_id=?',(chat_id,user_id())).fetchone():
            raise HTTPException(404,'Чат не знайдено')
        photo_id = uuid.uuid4().hex if photo is not None else None
        if photo_id:
            c.execute('INSERT INTO photos(id,chat_id,data,user_id) VALUES (?,?,?,?)', (photo_id,chat_id,photo,user_id()))
        c.execute(
            "INSERT INTO messages (chat_id, role, content, pages, created_at, sources,photo_id,user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, role, content, json.dumps(pages or []), _now(), json.dumps(sources or [], ensure_ascii=False),photo_id,user_id()),
        )
        if role == "user":  # назва чату = перше питання
            c.execute(
                "UPDATE chats SET title = ? WHERE id = ? AND user_id=? AND title IS NULL",
                (content[:50],chat_id,user_id()),
            )


def get_photo(chat_id, photo_id):
    with _conn() as c:
        row = c.execute('SELECT data FROM photos WHERE id = ? AND chat_id = ? AND user_id=?', (photo_id,chat_id,user_id())).fetchone()
        return row['data'] if row else None
