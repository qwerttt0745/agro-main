"""Private user-supplied label photos, not verified application instructions."""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from app import db, config, photos
router=APIRouter()
class LabelUpload(BaseModel):
    name:str=Field(min_length=1,max_length=150)
    note:str=Field(default='',max_length=2000)
    photo:str=Field(min_length=1,max_length=8*1024*1024)
    @field_validator('name')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('Вкажіть назву препарату')
        return v.strip()
def setup(c):
    c.execute('CREATE TABLE IF NOT EXISTS product_labels(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,note TEXT NOT NULL,image BLOB NOT NULL,created_at TEXT NOT NULL)')
@router.get('/labels')
def page():return FileResponse(config.ROOT/'static/labels.html')
@router.get('/api/labels')
def listing():
    with db._conn() as c:
        setup(c)
        return [dict(r) for r in c.execute('SELECT id,name,note,created_at FROM product_labels ORDER BY id DESC')]
@router.post('/api/labels')
def upload(value:LabelUpload):
    try:image=photos.prepare(value.photo)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    with db._conn() as c:
        setup(c)
        if c.execute('SELECT count(*) FROM product_labels').fetchone()[0]>=200:raise HTTPException(422,'Досягнуто ліміт 200 фото етикеток.')
        row=c.execute('INSERT INTO product_labels(name,note,image,created_at) VALUES (?,?,?,?)',(value.name,value.note,image,datetime.now(timezone.utc).isoformat()))
        return {'id':row.lastrowid,'status':'unverified'}
@router.get('/api/labels/{label_id}/image')
def image(label_id:int):
    with db._conn() as c:
        setup(c);r=c.execute('SELECT image FROM product_labels WHERE id=?',(label_id,)).fetchone()
    if not r:raise HTTPException(404,'Фото не знайдено')
    return Response(r['image'],media_type='image/jpeg',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
@router.delete('/api/labels/{label_id}')
def remove(label_id:int):
    with db._conn() as c:
        setup(c)
        if not c.execute('DELETE FROM product_labels WHERE id=?',(label_id,)).rowcount:raise HTTPException(404,'Фото не знайдено')
    return {'deleted':True}
