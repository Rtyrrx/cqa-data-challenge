from cqa.domain import Conversation
from cqa.tone import tone_observations
from test_backend import source


def build(language,turns):
    payload=source(language=language)
    payload['transcript']=[{'timestamp':f'00:{i:02d}','speaker':role,'text':text} for i,(role,text) in enumerate(turns)]
    return Conversation.model_validate(payload)


def test_familiar_address_anywhere_in_operator_dialogue_is_flagged():
    c=build('RU',[('operator','Здравствуйте, я Иван.'),('client','Что дальше?'),('operator','Тебе нужно открыть профиль.')])
    hints=tone_observations(c)['possible_informal_address']
    assert hints==[{'turn':3,'markers':['Тебе']}]


def test_kazakh_sen_and_siz_are_distinguished():
    c=build('KZ',[('operator','Сіз қосымшаны аша аласыз.'),('operator','Сен профильді аш.')])
    assert tone_observations(c)['possible_informal_address']==[{'turn':2,'markers':['Сен']}]


def test_formal_lowercase_absent_pronouns_and_english_you_are_not_flagged():
    for lang,text in [('RU','вы можете открыть профиль.'),('RU','Откройте профиль, пожалуйста.'),('KZ','сіз профильді аша аласыз.'),('EN','Hello, you can open your profile.')]:
        assert tone_observations(build(lang,[('operator',text)]))['possible_informal_address']==[]


def test_quotes_client_bot_internal_hold_and_disconnected_speech_are_excluded():
    c=build('RU',[
        ('client','Ты мне помоги.'),('bot','Тебе нужно открыть профиль.'),
        ('operator','Не используйте обращение «ты» и слово "тебя".'),
        ('system','Клиент находится на удержании.'),('operator','Ты проверь заявку.'),
        ('system','Клиент больше не находится на удержании.'),('operator','Вы на линии?'),
        ('system','Клиент завершил разговор.'),('operator','Тебе нужно проверить запись.'),
    ])
    assert tone_observations(c)['possible_informal_address']==[]


def test_hints_do_not_assert_an_automatic_violation():
    c=build('RU',[('operator','Клиент обратился на ты.')])
    result=tone_observations(c)
    assert result['possible_informal_address']
    assert 'not automatic violations' in result['instruction']
