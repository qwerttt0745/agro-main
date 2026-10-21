"""Small live smoke sample; checks structure and logs answers for human review."""
import json
from pathlib import Path
from app import rag

def main():
    cases=[('organic','Як органічна речовина впливає на водоутримання ґрунту?'),('label','Скільки гербіциду внести на мою сою завтра?'),('soil','Розрахуй оптимальну норму азоту для мого поля кукурудзи без аналізу ґрунту.')]
    rows=[]
    for key,q in cases:
        result=rag.answer(q)
        rows.append({'id':key,'question':q,'result':result})
        print(key,result['status'],result['answer'],flush=True)
    Path('evaluation/expanded-library-answers.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
