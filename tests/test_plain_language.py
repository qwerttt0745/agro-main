from app import rag,live
from app.language import PLAIN_UKRAINIAN


def test_same_plain_language_policy_covers_text_photo_and_voice():
    for prompt in (rag.SYSTEM,rag.PHOTO_SYSTEM,live.SYSTEM):
        assert PLAIN_UKRAINIAN in prompt
        assert '«посів» замість «сівба»' in prompt
        assert '«районований сорт»' in prompt
        assert 'коротко поясни' in prompt
        assert 'цитату дослівно' in prompt


def test_fixed_field_data_response_uses_familiar_words():
    result=rag.special_response('скільки добрив','field_data_required')
    assert 'що росло раніше' in result['answer']
    assert 'попередник' not in result['answer']
    assert 'цільова врожайність' not in result['answer']
