import unittest
from app.rag import join_page_chunks
from scripts.ingest import split
from scripts.evaluate import check_answer


class EvaluationTests(unittest.TestCase):
    def test_page_reconstruction_preserves_original_text(self):
        text = ' '.join(f'Слово{i}' for i in range(300))
        chunks = split(text)
        self.assertGreater(len(chunks), 2)
        self.assertEqual(join_page_chunks(chunks), text)

    def test_nonoverlapping_and_short_repeats_are_preserved(self):
        self.assertEqual(join_page_chunks(['Дані 10 кг', '10 кг наступна норма']), 'Дані 10 кг 10 кг наступна норма')
        self.assertEqual(join_page_chunks([]), '')

    def test_negative_needs_status_and_no_citations(self):
        case = {'unanswerable': True, 'expected_statuses': ['needs_field_data']}
        self.assertTrue(check_answer(case, {'status':'needs_field_data','answer':'Уточніть','sources':[]}))
        self.assertFalse(check_answer(case, {'status':'answered','answer':'Чорнозем','sources':[]}))
        self.assertFalse(check_answer(case, {'status':'needs_field_data','answer':'Уточніть','sources':[{}]}))

    def test_correct_citation_alone_does_not_pass_mass_regression(self):
        case = {'expected_document':'book.pdf','expected_page':83,'answer_contains':['30–37,5 м²'],'answer_excludes':['мільйон']}
        result = {'status':'answered','answer':'Мільйон гектарів','sources':[{'document':'book.pdf','page':83}]}
        self.assertFalse(check_answer(case,result))
        result['answer'] = '30–37,5 м²'
        self.assertTrue(check_answer(case,result))
