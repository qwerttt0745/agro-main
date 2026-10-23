"""User supplied facts and regional estimates; unknown soil values stay unknown."""
import json
from app import config


def private_json(name):
    from app import db
    from app.identity import user_id
    with db._conn() as c:
        row=c.execute('SELECT payload FROM user_documents WHERE user_id=? AND name=?',(user_id(),name)).fetchone()
    return json.loads(row['payload']) if row else {}


def profile():
    return private_json('farm_profile.json')


def location():
    from app.locations import Location
    from pydantic import ValidationError
    p=profile()
    try:
        value=Location.model_validate({k:p[k] for k in ('latitude','longitude') if k in p})
    except ValidationError:
        value=Location()
    legacy=p.get('location')
    name=p.get('location_name',legacy if isinstance(legacy,str) else '')
    return {**value.model_dump(),'location_name':name if isinstance(name,str) else ''}


def save_location(value):
    from app import db
    from app.identity import user_id
    # Read/merge/write under one SQLite write lock to preserve unrelated keys.
    with db._conn() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT payload FROM user_documents WHERE user_id=? AND name=?',(user_id(),'farm_profile.json')).fetchone()
        p=json.loads(row['payload']) if row else {}
        p.update(value.model_dump())
        c.execute('INSERT INTO user_documents(user_id,name,payload) VALUES (?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET payload=excluded.payload',
                  (user_id(),'farm_profile.json',json.dumps(p,ensure_ascii=False)))
    return value.model_dump()


def climate():
    return private_json('site/summary.json')


def context():
    p = profile()
    if not p:
        return ''
    return ('Відомості користувача: Культури: ' + ', '.join(p.get('crops',[])) +
            '. Якщо у запиті немає окремих записів поля чи даних користувача, межі, площа, тип ґрунту, pH, гумус, N/P/K, попередники, сорти, зрошення та моделі техніки невідомі. '
            'Не трактуй список культур як підтверджену сівозміну. Не роби висновків про ґрунт із координат. '
            'Для конкретного плану живлення потрібні аналіз ґрунту з методом і одиницями, культура, попередник, цільова врожайність та історія внесення.')


def nitrogen_amount(area_ha, target_n_kg_ha, n_percent):
    """Pure mass balance: target is supplied, never chosen by this calculator."""
    product_kg_ha = target_n_kg_ha / (n_percent / 100)
    return {'product_kg_ha': round(product_kg_ha, 2),
            'product_total_kg': round(product_kg_ha * area_ha, 2),
            'nitrogen_total_kg': round(target_n_kg_ha * area_ha, 2),
            'formula': 'Маса добрива = задана маса N / (N% / 100)',
            'limitation': 'Арифметичний перерахунок для добрива з відомою масовою часткою N. Не визначає потребу поля, засвоєння, втрати, строки чи спосіб внесення. Для літрів потрібна густина.'}


def nutrient_amount(area_ha, target_kg_ha, basis, n_percent, p2o5_percent, k2o_percent, density_kg_l=None):
    fractions={'N':n_percent,'P2O5':p2o5_percent,'K2O':k2o_percent}
    selected=fractions[basis]
    if selected<=0:raise ValueError('Обраний компонент має бути присутній у добриві.')
    rate=target_kg_ha*100/selected
    return {'product_kg_ha':round(rate,2),'product_total_kg':round(rate*area_ha,2),
            'nutrients_kg_ha':{k:round(rate*v/100,2) for k,v in fractions.items()},
            'product_l_ha':round(rate/density_kg_l,2) if density_kg_l else None,
            'product_total_l':round(rate*area_ha/density_kg_l,2) if density_kg_l else None,
            'basis':basis,'formula':'Маса продукту = задана кількість компонента × 100 / його масова частка, %',
            'limitation':'Розрахунок за введеною етикеткою, без підбору агрономічної норми. Інші компоненти надходять одночасно: звірте їх із планом живлення. P₂O₅ і K₂O не є елементарними P і K. Літри розраховуються за введеною густиною, яка залежить від продукту й температури. Не визначає доступність, втрати, сумісність або строки внесення.'}
