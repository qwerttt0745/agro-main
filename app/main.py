from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# Імпортуємо твої модулі бази даних та RAG
from app import db, rag, config, library, photos, model_pool, auth, weather, live, registers, fields, labels, locations
from contextlib import asynccontextmanager
from app.performance import request as performance_request
import logging

@asynccontextmanager
async def lifespan(app):
    auth.check_ready()
    db.init()
    yield

app = FastAPI(lifespan=lifespan)
app.middleware("http")(auth.protect)
app.include_router(auth.router)
app.include_router(live.router)
app.include_router(fields.router)
app.include_router(labels.router)
app.include_router(locations.router)

# Підключаємо папку зі статичними файлами (JS, CSS тощо)
app.mount("/static", StaticFiles(directory=str(config.ROOT / "static")), name="static")

class Question(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    photo: str | None = Field(default=None, max_length=8 * 1024 * 1024)

    @field_validator("text")
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Питання не може бути порожнім")
        return value

# Відкриття головної сторінки index.html
@app.get("/")
def read_root():
    return FileResponse(config.ROOT / "static/index.html")

@app.post("/chats")
def new_chat():
    return {"id": db.create_chat()}

@app.get("/chats")
def chats():
    return db.list_chats()

@app.get("/chats/{chat_id}")
def chat(chat_id: int):
    if not db.chat_exists(chat_id):
        raise HTTPException(404, "Чат не знайдено")
    return db.get_messages(chat_id)

@app.post("/chats/{chat_id}/ask")
def ask(chat_id: int, q: Question):
    if not db.chat_exists(chat_id):
        raise HTTPException(404, "Чат не знайдено")
    
    try:
        image = photos.prepare(q.photo) if q.photo is not None else None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    history = db.get_messages(chat_id)[-12:]

    # 1. Зберігаємо запитання користувача в базу
    db.add_message(chat_id, "user", q.text, photo=image)
    
    return generate_reply(chat_id, q.text, image, history)


def generate_reply(chat_id, text, image, history):
    try:
        with performance_request('photo' if image else 'text'):
            result = rag.answer_photo(text, image, history) if image else rag.answer(text, history)
    except rag.ServiceUnavailable as exc:
        # No assistant row for temporary failures: retry reuses the saved user row/photo.
        waits = [s['retry_after'] for s in model_pool.status()]
        return {'answer':str(exc), 'pages':[], 'sources':[], 'status':'unavailable',
                'retryable':exc.status_code != 502,
                'retry_after':min(waits) if waits and all(waits) else 0}
    except Exception as exc:
        logging.getLogger(__name__).error("Answer failed for chat %s (%s)", chat_id,type(exc).__name__)
        raise HTTPException(503, "Не вдалося отримати відповідь. Питання збережено в історії. Спробуйте пізніше.") from exc
    db.add_message(chat_id, "assistant", result["answer"], result["pages"], result.get("sources", []))
    return result


@app.post('/chats/{chat_id}/retry')
def retry_question(chat_id: int):
    if not db.chat_exists(chat_id):
        raise HTTPException(404, 'Чат не знайдено')
    messages = db.get_messages(chat_id)
    if not messages or messages[-1]['role'] != 'user':
        raise HTTPException(409, 'Немає запиту, що очікує відповіді')
    latest = messages[-1]
    image = db.get_photo(chat_id, latest['photo_url'].rsplit('/',1)[-1]) if latest.get('photo_url') else None
    return generate_reply(chat_id, latest['content'], image, messages[:-1][-12:])


@app.get('/api/models')
def models_status():
    return {'mode':'auto', 'models':model_pool.status(),
            'note':'Порядок пріоритету; доступність перевіряється під час запиту. Free tier залежить від тарифу проєкту Google.'}


@app.get("/library/{document_id}/pdf")
def library_pdf(document_id: str):
    path = library.files().get(document_id)
    if path is None:
        raise HTTPException(404, "Документ не знайдено")
    return FileResponse(path, media_type="application/pdf")

from app import farm

class NitrogenCalculation(BaseModel):
    area_ha: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    target_n_kg_ha: float = Field(ge=0, le=10000, allow_inf_nan=False)
    n_percent: float = Field(ge=0.01, le=100, allow_inf_nan=False)

@app.get('/farm')
def farm_page():
    return FileResponse(config.ROOT / 'static/farm.html')

@app.get('/api/farm')
def farm_data():
    return {'profile': farm.profile(), 'climate': farm.climate(), 'library': library.catalog()}

@app.post('/api/calculations/nitrogen')
def calculate_nitrogen(values: NitrogenCalculation):
    return farm.nitrogen_amount(**values.model_dump())


@app.get('/chats/{chat_id}/photos/{photo_id}')
def chat_photo(chat_id: int, photo_id: str):
    image = db.get_photo(chat_id, photo_id)
    if image is None:
        raise HTTPException(404, 'Фото не знайдено')
    return Response(image, media_type='image/jpeg', headers={'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})


@app.get('/live')
def live_page():
    return FileResponse(config.ROOT / 'static/live.html')


@app.get('/api/weather')
def weather_data(field_id: int | None = Query(default=None,gt=0)):
    try:
        return weather.forecast(field_id=field_id) if field_id is not None else weather.forecast()
    except weather.WeatherUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


class RegisterQuery(BaseModel):
    kind: str = Field(pattern='^(pesticides|varieties)$')
    query: str = Field(min_length=2,max_length=150)

@app.get('/api/registers')
def register_status():
    return [{**registers.metadata(k),'kind':k,'title':v['title'],'fresh_check':registers.fresh(registers.metadata(k))} for k,v in registers.SOURCES.items()]

@app.post('/api/registers/search')
def register_search(query:RegisterQuery):
    try:return registers.search(query.kind,query.query)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


@app.get('/registers/{digest}/xlsx')
def register_snapshot(digest:str):
    import re
    if not re.fullmatch(r'[a-f0-9]{64}',digest):raise HTTPException(404,'Копію не знайдено')
    path=config.DATA/'registers'/(digest+'.xlsx')
    if not path.is_file() or not path.resolve().is_relative_to((config.DATA/'registers').resolve()):raise HTTPException(404,'Копію не знайдено')
    return FileResponse(path,filename='official-register-'+digest[:12]+'.xlsx')


class NutrientCalculation(BaseModel):
    area_ha: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    target_kg_ha: float = Field(ge=0, le=10000, allow_inf_nan=False)
    basis: str = Field(pattern=r'^(N|P2O5|K2O)$')
    n_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    p2o5_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    k2o_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    density_kg_l: float | None = Field(default=None, gt=0, le=10, allow_inf_nan=False)


@app.post('/api/calculations/nutrients')
def calculate_nutrients(values: NutrientCalculation):
    try:return farm.nutrient_amount(**values.model_dump())
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
