"""User supplied facts and regional estimates; unknown soil values stay unknown."""
import json
from app import config


def profile():
    path = config.DATA / 'farm_profile.json'
    return json.loads(path.read_text()) if path.exists() else {}


def climate():
    path = config.DATA / 'site/summary.json'
    return json.loads(path.read_text()) if path.exists() else {}


def context():
    p = profile()
    if not p:
        return ''
    return ('Відомості користувача: господарство біля Паволочі. Культури: ' + ', '.join(p['crops']) +
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
