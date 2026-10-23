"""User-reported cultivation questions must not turn into unrelated refusal templates."""
import json
from unittest.mock import Mock,patch
import pytest
from app import rag,intent

TEXT='Пшениця потребує родючого ґрунту. Важливо правильно обрати попередник.'
CHUNKS=[{'id':'S1','source':'book.pdf','page':1,'text':TEXT}]


def raw(**changes):
    return json.dumps({'answer':'Оберіть родючий ґрунт і відповідного попередника [S1].','insufficient':False,
        'evidence':[{'source_id':'S1','quote':TEXT}],**changes},ensure_ascii=False)


@pytest.mark.parametrize('question',[
 'Як правильно вирощувати пшеницю',
 'Ну напиши як правильно вирощувати',
 'Які основні етапи вирощування кукурудзи?',
 'де садить пшеницю?',
])
def test_recognizes_general_cultivation(question):
    assert intent.general_cultivation(question)


@pytest.mark.parametrize('question',[
 'Як вирощувати пшеницю та який гербіцид внести?',
 'Як вирощувати пшеницю, скільки азоту внести?',
 'Яка норма добрив для мого поля?',
 'Як обприскувати пшеницю?',
])
def test_explicit_prescriptions_keep_original_guardrails(question):
    assert not intent.general_cultivation(question)
    data=raw(pesticide_application=True)
    assert rag.validate_answer(data,CHUNKS,question)['status']=='label_required'


@pytest.mark.parametrize('flag',['pesticide_application','needs_field_data'])
def test_valid_general_answer_survives_mistaken_model_flag(flag):
    with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'retrieve',return_value=CHUNKS),patch.object(rag,'_generate',return_value=raw(**{flag:True})):
        result=rag.answer('Як правильно вирощувати пшеницю')
    assert result['status']=='answered'
    assert result['sources'][0]['quote']==TEXT
    assert 'родючий' in result['answer']
    assert 'Для конкретної обробки' not in result['answer']


def test_followup_resolves_crop_only_from_user_history_without_model_rewrite():
    history=[{'role':'user','content':'Як правильно вирощувати пшеницю'},
             {'role':'assistant','content':'Потрібен план живлення кукурудзи.'}]
    with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'retrieve',return_value=CHUNKS) as retrieve,patch.object(rag,'standalone_question') as rewrite,patch.object(rag,'_generate',return_value=raw(needs_field_data=True)):
        result=rag.answer('Ну напиши як правильно вирощувати',history)
    assert result['status']=='answered'
    assert 'пшениця' in retrieve.call_args.args[0]
    assert 'кукурудз' not in retrieve.call_args.args[0]
    rewrite.assert_not_called()


def test_general_route_still_rejects_fabricated_citations():
    data=raw(pesticide_application=True,evidence=[{'source_id':'S1','quote':'Цієї цитати на сторінці немає.'}])
    assert rag.validate_answer(data,CHUNKS,'Як вирощувати пшеницю?',general_overview=True)['status']=='invalid_evidence'


@pytest.mark.parametrize('answer',[
 'Внесіть 30 кг/га азоту [S1].',
 'Обприскайте препаратом 0.5 л/га [S1].',
 'Добрива: 20–30 кг/га [S1].',
])
def test_general_route_rejects_concrete_product_or_nutrient_rates(answer):
    assert intent.contains_prescription(answer)
    assert rag.validate_answer(raw(answer=answer),CHUNKS,'Як вирощувати пшеницю?',general_overview=True)['status']=='scope_mismatch'


def test_prescription_in_general_draft_is_repaired_to_grounded_overview():
    with patch.object(rag,'resources',return_value=Mock()),patch.object(rag,'retrieve',return_value=CHUNKS),patch.object(rag,'_generate',side_effect=[raw(answer='Внесіть 30 кг/га азоту [S1].',needs_field_data=True),raw()]) as generate:
        result=rag.answer('Як правильно вирощувати пшеницю?')
    assert result['status']=='answered'
    assert generate.call_count==2
    assert 'загальний практичний огляд' in generate.call_args.args[0]
