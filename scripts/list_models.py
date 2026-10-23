"""Inspect key-visible model metadata. Probing generation requires --probe."""
import argparse
import json
import os
from google import genai
from google.genai import types
from pydantic import BaseModel
from app import config, model_pool


class Check(BaseModel):
    description:str


def inventory(client):
    rows={}
    for model in client.models.list(config=types.ListModelsConfig(page_size=100)):
        name=(model.name or '').removeprefix('models/')
        if name:rows[name]=set(model.supported_actions or [])
    configured=model_pool.configured_models()
    return {'listed_total':len(rows),
            'generate_content_total':sum('generateContent' in actions for actions in rows.values()),
            'configured_total':len(configured),
            'configured':[{'model':name,'listed':name in rows,'generate_content':'generateContent' in rows.get(name,set())} for name in configured],
            'generate_content_models':sorted(name for name,actions in rows.items() if 'generateContent' in actions),
            'note':'Listed metadata does not confirm free pricing, available quota, JSON/image support or successful generation.'}


def probe(client,models):
    results=[]
    for name in models:
        try:
            response=client.models.generate_content(model=name,contents='Напиши слово готово у полі description.',
                config=types.GenerateContentConfig(response_mime_type='application/json',response_schema=Check,
                    thinking_config=types.ThinkingConfig(thinking_level='LOW') if name in ('gemini-3.8-flash','gemini-3.6-flash','gemini-3-flash-preview') else None,
                    http_options=types.HttpOptions(timeout=8000,retry_options=types.HttpRetryOptions(attempts=1))))
            Check.model_validate_json(response.text)
            results.append({'model':name,'generation':'ok'})
        except Exception as exc:
            code=getattr(exc,'code',None)
            # Never print provider exception messages, request URLs or credentials.
            results.append({'model':name,'generation':'failed','error_type':type(exc).__name__,
                            'http_code':code if isinstance(code,int) else None})
    return results


def main():
    parser=argparse.ArgumentParser(description='Перелік моделей для поточного ключа. Без ключів і текстів помилок у виводі.')
    parser.add_argument('--probe',action='store_true',help='Виконати коротку JSON-генерацію на кожній видимій моделі пулу; витрачає квоту і може бути платним залежно від тарифу.')
    args=parser.parse_args()
    key=os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not key:raise SystemExit('Не налаштовано ключ Gemini. Запускайте команду в контейнері app.')
    try:
        with genai.Client(api_key=key,http_options=types.HttpOptions(timeout=10000,retry_options=types.HttpRetryOptions(attempts=1))) as client:
            result=inventory(client)
            if args.probe:
                result['probes']=probe(client,[row['model'] for row in result['configured'] if row['generate_content']])
    except Exception as exc:
        code=getattr(exc,'code',None)
        print(json.dumps({'error_type':type(exc).__name__,'http_code':code if isinstance(code,int) else None}))
        raise SystemExit(1) from None
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
