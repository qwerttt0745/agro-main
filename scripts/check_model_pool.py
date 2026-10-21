"""Small live router check; no user data, billing settings, or keys in output."""
import io
import json
from pathlib import Path
from PIL import Image
from pydantic import BaseModel
from google.genai import types
from app import rag, model_pool

class Check(BaseModel):
    description: str

def main():
    results=[]
    image=io.BytesIO();Image.new('RGB',(100,100),'green').save(image,format='JPEG')
    for kind,contents in [('text','Напиши слово «готово» у полі description.'),
                          ('photo',[types.Part.from_bytes(data=image.getvalue(),mime_type='image/jpeg'),'Опиши зображення одним коротким реченням у полі description.'])]:
        try:
            raw=rag._generate(contents,response_schema=Check,request_timeout=30)
            result={'kind':kind,'result':Check.model_validate_json(raw).model_dump()}
        except Exception as exc:
            result={'kind':kind,'error':type(exc).__name__}
        result['models']=model_pool.status();results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    Path('evaluation/model-pool-smoke.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
