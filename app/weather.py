"""Timestamped model forecasts; never measurements of the field."""
import copy
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
from app import farm

_lock = threading.Lock()
_cache = None
_retry_at = 0
TTL = 900


class WeatherUnavailable(RuntimeError):
    pass


def forecast():
    global _cache, _retry_at
    p = farm.profile()
    point = (p.get('latitude'), p.get('longitude'))
    if None in point:
        raise WeatherUnavailable('Спочатку потрібні координати господарства.')
    with _lock:
        now = time.time()
        cached = _cache if _cache and _cache['point'] == point else None
        if cached and now - cached['at'] < TTL:
            return copy.deepcopy(cached['data'])
        if now < _retry_at:
            raise WeatherUnavailable('Погодний сервіс тимчасово недоступний. Повторіть за хвилину.')
        key = os.getenv('OPEN_METEO_API_KEY')
        params = {'latitude':point[0], 'longitude':point[1], 'timezone':'Europe/Kyiv',
                  'forecast_days':7, 'wind_speed_unit':'ms',
                  'current':'temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m',
                  'hourly':'temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,soil_temperature_6cm',
                  'daily':'temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max'}
        url = 'https://customer-api.open-meteo.com/v1/forecast' if key else 'https://api.open-meteo.com/v1/forecast'
        if key:
            params['apikey'] = key
        try:
            response = requests.get(url, params=params, timeout=(3, 7))
            response.raise_for_status()
            raw = response.json()
            daily = raw['daily']
            dates = daily['time']
            if not dates or dates[0] != datetime.now(ZoneInfo('Europe/Kyiv')).date().isoformat():
                raise ValueError('Old forecast')
            fields = ['temperature_2m_min','temperature_2m_max','precipitation_sum',
                      'precipitation_probability_max','wind_speed_10m_max','wind_gusts_10m_max']
            days = [{'date':d, **{f:daily[f][i] for f in fields}} for i,d in enumerate(dates)]
            data = {'source':'Open-Meteo', 'source_url':'https://open-meteo.com/',
                    'retrieved_at':datetime.now(timezone.utc).isoformat(), 'timezone':'Europe/Kyiv',
                    'requested_point':{'latitude':point[0], 'longitude':point[1]},
                    'grid_point':{'latitude':raw.get('latitude'),'longitude':raw.get('longitude')},
                    'current':raw['current'], 'current_units':raw['current_units'],
                    'hourly':raw['hourly'], 'hourly_units':raw['hourly_units'],
                    'days':days, 'daily_units':raw['daily_units'],
                    'note':'Модельний прогноз для околиць точки, не вимірювання на полі. Час — Київ. Прогноз не гарантує опадів; стан конкретного поля потрібно перевірити на місці.'}
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            _retry_at = now + 60
            raise WeatherUnavailable('Не вдалося оновити прогноз. Застарілі значення не видаються як поточна погода.') from exc
        _cache = {'point':point, 'at':now, 'data':data}
        return copy.deepcopy(data)


def is_question(question):
    return bool(re.search(r'погод|прогноз|дощ|опад|вітер|вітру|замороз|примороз|температур',question.lower()))


def simple_question(question):
    q=question.lower()
    return is_question(q) and not field_work(q) and not re.search(r'сія|сівб|обприск|гербіц|фунгіц|добрив|внес|піджив|ґрунт|грунт|рослин|культур|вплив|чому|торік|минул|істор|клімат',q)


def answer(question):
    try:
        data=forecast()
    except WeatherUnavailable as exc:
        return {'answer':str(exc),'pages':[],'sources':[],'status':'weather_unavailable'}
    fmt=lambda v: 'немає даних' if v is None else str(v).replace('.',',')
    lines=['Прогноз для точки господарства біля Паволочі (час Києва):']
    current=data.get('current',{})
    if current.get('time'):
        lines.append(f"Поточна модельна оцінка на {current['time']}: {fmt(current.get('temperature_2m'))} °C; вітер {fmt(current.get('wind_speed_10m'))} м/с, пориви {fmt(current.get('wind_gusts_10m'))} м/с.")
    # Show exact dates rather than guessing an arbitrary requested date or place.
    days=data['days'] if re.search(r'тиж|7 д|сім д',question.lower()) else data['days'][:3]
    q=question.lower()
    if 'післязавтра' in q:days=days[2:3]
    elif 'завтра' in q:days=days[1:2]
    elif 'сьогодні' in q or 'зараз' in q:days=days[:1]
    for day in days:
        lines.append(f"{day['date']}: {fmt(day['temperature_2m_min'])}…{fmt(day['temperature_2m_max'])} °C; опади {fmt(day['precipitation_sum'])} мм, імовірність до {fmt(day['precipitation_probability_max'])}%; вітер до {fmt(day['wind_speed_10m_max'])} м/с, пориви до {fmt(day['wind_gusts_10m_max'])} м/с.")
    lines.extend([data['note'], 'Джерело: https://open-meteo.com/ · Оновлено '+data['retrieved_at']])
    return {'answer':'\n\n'.join(lines),'pages':[],'sources':[],'status':'weather','weather':data}


def field_work(question):
    return bool(re.search(r'молот|обмолот|збир|збира|жнив|комбай|косити|косін|сія|сівб|обприск|внес|піджив|виїх|проїха|пол[еіяю]|підійде|працюва', question.lower()))


def needs_context(question):
    return is_question(question) or (field_work(question) and bool(re.search(r'зараз|сьогодні|завтра|нині|тижн|понеділ|вівтор|серед|четвер|п’ятниц|пятниц|субот|неділ',question.lower())))


def requested_day(question, today=None):
    today=today or datetime.now(ZoneInfo('Europe/Kyiv')).date()
    q=question.lower()
    for i,stem in enumerate(('понеділ','вівтор','серед','четвер','п’ятниц','субот','неділ')):
        if stem in q.replace("'",'’'):
            return today+timedelta(days=(i-today.weekday())%7 or 7)
    return None


def context_chunk(source_id):
    """Freeze a small weather snapshot as citable evidence for one answer."""
    data=forecast()
    fmt=lambda v:'немає даних' if v is None else str(v).replace('.',',')
    c=data.get('current',{})
    lines=[f"Open-Meteo, точка господарства біля Паволочі. Отримано {data['retrieved_at']}. Час прогнозу: Europe/Kyiv."]
    lines.append(f"Поточна модельна оцінка {c.get('time','час невідомий')}: температура {fmt(c.get('temperature_2m'))} °C; відносна вологість повітря {fmt(c.get('relative_humidity_2m'))} %; вітер {fmt(c.get('wind_speed_10m'))} м/с; пориви {fmt(c.get('wind_gusts_10m'))} м/с.")
    for d in data.get('days',[]):
        lines.append(f"{d['date']}: температура {fmt(d.get('temperature_2m_min'))}…{fmt(d.get('temperature_2m_max'))} °C; опади за добу {fmt(d.get('precipitation_sum'))} мм; максимальна ймовірність опадів {fmt(d.get('precipitation_probability_max'))} %.")
    h=data.get('hourly',{});now=datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%dT%H:00')
    upcoming=[(i,t) for i,t in enumerate(h.get('time',[])) if t>=now][:6]
    for i,t in upcoming:
        value=lambda key:fmt(h[key][i] if key in h and i<len(h[key]) else None)
        lines.append(f"{t}: опади {value('precipitation')} мм; імовірність {value('precipitation_probability')} %; вітер {value('wind_speed_10m')} м/с; пориви {value('wind_gusts_10m')} м/с.")
    lines.append('Це модельний прогноз. Вологість зерна, стиглість, роса на рослинах, несуча здатність ґрунту і наявність сушарки цими даними не визначені. Вологість повітря не є вологістю зерна.')
    return {'id':source_id,'source':'Open-Meteo','page':None,'kind':'weather','text':'\n'.join(lines),'retrieved_at':data['retrieved_at']}
