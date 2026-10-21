"""Repeatable checks against the local index; --answers also calls Gemini."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from app import config, rag, intent, model_pool


def check_answer(case, result):
    """Necessary regression conditions, not a semantic correctness verdict."""
    statuses = case.get('expected_statuses', ['insufficient'] if case.get('unanswerable') else ['answered'])
    if result['status'] not in statuses:
        return False
    answer = result['answer'].casefold()
    if any(term.casefold() not in answer for term in case.get('answer_contains', [])):
        return False
    if any(term.casefold() in answer for term in case.get('answer_excludes', [])):
        return False
    if case.get('unanswerable') or case.get('requires_live_data'):
        return not result.get('sources')
    return any(s['document'] == case['expected_document'] and
               s['page'] == case['expected_page'] for s in result.get('sources', []))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--answers', action='store_true')
    parser.add_argument('--ids', nargs='+', help='Run only these case IDs')
    parser.add_argument('--include-text', action='store_true', help='Include full retrieved passages')
    parser.add_argument('--output', type=Path, default=config.ROOT / 'evaluation/latest.json')
    args = parser.parse_args()
    cases = json.loads((config.ROOT / 'evaluation/questions.json').read_text())
    if args.ids:
        unknown = set(args.ids) - {c['id'] for c in cases}
        if unknown:
            parser.error('Unknown IDs: ' + ', '.join(sorted(unknown)))
        cases = [c for c in cases if c['id'] in args.ids]
    rows = []
    for case in cases:
        search_q = intent.search_terms(case['question'])
        chunks = rag.retrieve(search_q)
        positive = bool(case.get('expected_document'))
        hit = any(Path(c['source']).name == case.get('expected_document') and
                  c['page'] == case.get('expected_page') and
                  case.get('expected_text', '') in c['text'] for c in chunks) if positive else None
        retrieved = chunks if args.include_text else [{k: v for k, v in c.items() if k != 'text'} for c in chunks]
        row = {'id': case['id'], 'question': case['question'], 'search_query': search_q,
               'retrieval_hit': hit, 'retrieved': retrieved}
        if args.answers:
            try:
                result = rag.answer(case['question'], case.get('history'))
                row['result'] = result
                row['answer_check'] = check_answer(case, result)
            except rag.ServiceUnavailable as exc:
                row['error'] = {'status': exc.status_code, 'message': str(exc)}
                row['answer_check'] = False
        rows.append(row)
        print(case['id'], 'retrieval_hit=', hit, 'answer_check=', row.get('answer_check'), flush=True)
    positives = [r for r in rows if r['retrieval_hit'] is not None]
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'eligible_models_at_end': model_pool.candidates(),
              'top_k': 10, 'page_expansion': True, 'positive_hits': sum(r['retrieval_hit'] for r in positives),
              'positive_count': len(positives),
              'answer_checks_passed': sum(r.get('answer_check', False) for r in rows) if args.answers else None,
              'cases': rows,
              'limits': 'Small regression sample, not an agronomic quality guarantee. Distance is not confidence. Negative retrieval has no automatic pass threshold. Answer checks verify status, selected terms and citation location, not semantic entailment. Model list is eligibility, not the actual model used. Retrieval-only mode does not rewrite dialogue.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return int(any(r['retrieval_hit'] is False or r.get('answer_check') is False for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
