"""Small deterministic helpers for field-data boundaries and seed arithmetic."""
import re
from decimal import Decimal


def soil_question(question):
    q=question.lower()
    return bool(re.search(r'чорнозем|тип.*(?:ґрунт|грунт|земл)|вид.*(?:ґрунт|грунт|земл)',q) and re.search(r'\bтут\b|мо[єїяє]|полі|паволоч|біля бази',q))


def seed_mass(question):
    q=question.lower()
    if 'греч' not in q or not re.search(r'площ|засія|посія|засе|висія',q):return None
    match=re.search(r'(\d+(?:[.,]\d+)?)\s*(кг|кілограм\w*|грам\w*|г)(?![\w/])',q)
    if not match:return None
    value=Decimal(match[1].replace(',','.'))
    if value<=0 or value>Decimal("1000000000"):return None
    return value if match[2].startswith(('кг','кіло')) else value/1000


def search_terms(question):
    if 'кукурудз' in question.lower() and re.search(r'молот|збир|збира|жнив|комбай',question.lower()):
        return 'кукурудза збирання на зерно стиглість вологість зерна обмолот сушіння'
    if seed_mass(question) is not None:
        return 'гречка норма висіву насіння кг/га звичайний рядковий широкорядний спосіб'
    return question


def seed_answer(question,chunks):
    kg=seed_mass(question)
    if kg is None:return None
    for chunk in chunks:
        if chunk['source'].rsplit('/',1)[-1]!='TVPR_2_2010.pdf':continue
        text=' '.join(chunk['text'].split())
        match=re.search(r'Норма висіву за звичайного рядкового.*?(\d+)-(\d+) кг/га.*?широкорядної сівби\s*[–—-]\s*(\d+)-(\d+) кг/га',text)
        if not match:continue
        low,high,wide_low,wide_high=map(Decimal,match.groups())
        if not (0<low<=high and 0<wide_low<=wide_high):continue
        fmt=lambda n:format(n.quantize(Decimal('0.01')),'f').rstrip('0').rstrip('.').replace('.',',')
        sid=chunk['id']
        answer=(f'Якщо йдеться про {fmt(kg*1000)} г **насіння** гречки, це {fmt(kg)} кг. '
                f'За навчальними нормами з посібника 2010 року цього вистачить орієнтовно на **{fmt(kg/high*10000)}–{fmt(kg/low*10000)} м²** '
                f'при звичайній рядковій сівбі ({fmt(low)}–{fmt(high)} кг/га) [{sid}]. '
                f'Для широкорядної сівби за наведеними у книзі {fmt(wide_low)}–{fmt(wide_high)} кг/га — **{fmt(kg/wide_high*10000)}–{fmt(kg/wide_low*10000)} м²** [{sid}].\n\n'
                'Розрахунок: площа, м² = маса насіння, кг ÷ норма, кг/га × 10 000. Це перерахунок за історичним навчальним орієнтиром, '
                'а не підібрана норма для вашого поля. Для точнішого значення потрібні спосіб сівби, схожість і маса 1000 насінин. '
                'Уточніть: це саме посівне насіння, а не крупа, і точно грами, не гектари?')
        return {'answer':answer,'insufficient':False,'evidence':[{'source_id':sid,'quote':match[0]}]}
    return None


def relevant_chunks(question, chunks):
    """Keep explicit crop context for corn harvest; generic cereal stages mislead."""
    if 'кукурудз' in question.lower() and re.search(r'молот|збир|збира|жнив|комбай', question.lower()):
        return [c for c in chunks if re.search(r'кукурудз|\bcorn\b|\bmaize\b', c['text'], re.I)]
    return chunks


def drying_answer(question):
    """Mass balance from explicit user measurements, excluding impurities/losses."""
    q=question.lower().replace('\u00a0',' ')
    mass=re.search(r'(?:початкова|фізична)[^:\n]*[:—]\s*([\d ,]+(?:[.]\d+)?)\s*кг',q)
    actual=re.search(r'фактична вологість[^:\n]*[:—]\s*(\d+(?:[.,]\d+)?)\s*%',q)
    target=re.search(r'(?:базова|цільова)[^:\n]*[:—]\s*(\d+(?:[.,]\d+)?)\s*%',q)
    if not all((mass,actual,target)):return None
    m=Decimal(mass[1].replace(' ','').replace(',','.'));a=Decimal(actual[1].replace(',','.'));b=Decimal(target[1].replace(',','.'))
    if not (m>0 and 0<=b<a<100):
        return {'answer':'Для розрахунку сушіння потрібна додатна маса та вологості від 0 до 100%, причому початкова має бути вищою за цільову. Перевірте введені числа.', 'pages':[], 'sources':[], 'status':'needs_field_data'}
    final=m*(100-a)/(100-b);water=m-final
    fmt=lambda v:format(v.quantize(Decimal('0.01')),'f').replace('.',',')
    return {'answer':f'Після сушіння з {fmt(a)}% до {fmt(b)}% із {fmt(m)} кг отримаєте приблизно **{fmt(final)} кг зерна**. Розрахункове зменшення маси через видалення води — **{fmt(water)} кг** ({fmt(water/m*100)}% початкової маси).\n\nФормула збереження сухої речовини: кінцева маса = {fmt(m)} × (100 − {fmt(a)}) ÷ (100 − {fmt(b)}).\n\nЦе теоретичний баланс за наданими вами числами: без очищення від домішок, втрат сухої речовини та похибки вимірювання. 14% тут — задана вами ціль, а не перевірений мною стандарт. Залікова маса за договором може відрізнятися. Фото не визначає вологість і не змінює цей розрахунок.', 'pages':[], 'sources':[], 'status':'calculated'}


_CROPS=(('пшениц','пшениця'),('греч','гречка'),('кукурудз','кукурудза'),('соняшник','соняшник'),('ріпак','ріпак'),('ячмін','ячмінь'),('со[яїю]','соя'))


def general_cultivation(question):
    """A broad growing overview is not a request for a chemical prescription."""
    q=question.lower()
    if seed_mass(question) is not None:return False
    broad=bool(re.search(r'(?:\b(?:як|де)\b|правильн|технолог|основ|етап|план|порад).*?(?:вирощ|сади|садж|сія)|(?:вирощ|сади|садж).*?(?:правильн|основ)',q))
    explicit=bool(re.search(r'гербіц|фунгіц|інсектиц|пестиц|обприск|протру|доз|бакова|бакову|строк.*очікуван|норм.*(?:добрив|азот|внес|піджив)|скільки.*(?:добрив|азот|внес|піджив)|план.*(?:живлен|удобр)',q))
    return broad and not explicit


def overview_question(question,history=None):
    """Resolve only the crop from actual user messages, never prior assistant refusals."""
    messages=[question]+[m['content'] for m in reversed((history or [])[-8:]) if m['role']=='user']
    for text in messages:
        for stem,name in _CROPS:
            if re.search(stem,text.lower()):return f'Як правильно вирощувати {name}?'
    return question


def contains_prescription(answer):
    """Reject concrete product/nutrient rates from the broad-overview route."""
    q=answer.lower()
    product=r'добрив|азот|карбамід|селітр|пестиц|гербіц|фунгіц|інсектиц|препарат|обприск|протру'
    rate=r'\d+(?:[.,]\d+)?\s*(?:[–—-]\s*\d+(?:[.,]\d+)?)?\s*(?:кг|л|г|мл|мг|kg|ml|l)\s*(?:/|на)\s*(?:га|гектар|л|літр|ha)'
    return any(re.search(product,part) and re.search(rate,part) for part in re.split(r'[!?;\n]|\.(?!\d)',q))
