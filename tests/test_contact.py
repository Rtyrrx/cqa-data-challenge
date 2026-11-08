import pytest

from cqa.contact import apply_contact_check, contact_observation
from cqa.domain import Conversation, Judgment, official_checklist
from cqa.service import Service
from test_backend import FakeModel, source, settings


def conversation(language,text,later=None):
    payload=source(language=language)
    payload['transcript'][-1]['text']=text
    if later:
        payload['transcript'].append({'timestamp':'00:04','speaker':'operator','text':later})
    return Conversation.model_validate(payload)


@pytest.mark.parametrize('language,text',[
    ('EN',"Hi, I'm Adrian. Open Quotes."),
    ('EN',"Hi, I'm Tyler. There is a restriction."),
    ('EN',"Hi, I'm Eva. Open «Кабинет» in the Russian interface."),
    ('EN','Hello, I am Maya.'),
    ('RU','Здравствуйте, я Тимур. Где вы сравнивали тарифы?'),
    ('RU','Добрый день! Я Лера из поддержки.'),
    ('RU','Здравствуйте! Меня зовут Алина.'),
    ('KZ','Сәлеметсіз бе, менің атым Аружан. «Кабинет» бөлімін ашыңыз.'),
    ('KZ','Сәлеметсіз бе! Мен Нұрланмын.'),
    ('KZ','Сәлеметсіз бе, мен Айбекпін.'),
])
def test_explicit_openings(language,text):
    c=conversation(language,text)
    observed=contact_observation(c)
    assert observed['confirmed']
    assert observed['turn']==4  # Not first transcript turn; bot and system preserved.
    j=Judgment(criterion_id='contact',value=False,rationale='Incorrect model denial.',evidence_turns=[1])
    trace=apply_contact_check(c,official_checklist().criteria,[j])
    assert j.value is True and j.evidence_turns==[4]
    assert trace['model_judgment_before_check']['value'] is False


@pytest.mark.parametrize('language,text',[
    ('EN','Open settings then log in again.'),
    ('EN','Hello. Open your settings.'),
    ('EN',"I'm Adrian. Open Quotes."),
    ('EN',"Hi, I'm Sorry about that."),
    ('RU','Здравствуйте, я проверю.'),
])
def test_unconfirmed_openings_are_not_auto_passed_or_failed(language,text):
    c=conversation(language,text)
    assert not contact_observation(c)['confirmed']
    j=Judgment(criterion_id='contact',value=False,rationale='Model judgment retained.',evidence_turns=[4])
    assert apply_contact_check(c,official_checklist().criteria,[j]) is None
    assert j.value is False


@pytest.mark.parametrize('language,text',[
    ('RU','Привет, меня зовут Иван. Чем помочь?'),
    ('RU','Здравствуй, я Тимур.'),
    ('RU','Привет, где именно ищете?'),
    ('KZ','Сәлем, мен Айбекпін. Қалай көмектесейін?'),
    ('KZ','Сәлеметсің бе, мен Дана.'),
    ('KZ','Сәлем. Қай сайтқа кірдіңіз?'),
])
def test_informal_native_greeting_fails_even_with_introduction(language,text):
    c=conversation(language,text)
    observed=contact_observation(c)
    assert observed['informal_greeting'] and not observed['confirmed']
    j=Judgment(criterion_id='contact',value=True,rationale='Model mistakenly passed.',evidence_turns=[4])
    trace=apply_contact_check(c,official_checklist().criteria,[j])
    assert j.value is False and j.evidence_turns==[4]
    assert 'business-tone policy' in j.rationale
    assert trace['model_judgment_before_check']['value'] is True


def test_lowercase_respectful_address_does_not_fail_contact():
    assert contact_observation(conversation('RU','Здравствуйте, я Иван. Вы можете открыть приложение.'))['confirmed']
    assert contact_observation(conversation('RU','Здравствуйте, я Иван. вы можете открыть приложение.'))['confirmed']
    assert contact_observation(conversation('KZ','Сәлеметсіз бе, мен Дана. сіз бөлімді аша аласыз.'))['confirmed']


def test_bot_greeting_and_later_introduction_do_not_count():
    c=conversation('EN','Hello. What do you need?',later="I'm Adrian.")
    c.transcript[1].text="Hi, I'm the bot."
    assert not contact_observation(c)['confirmed']


def test_changed_rubric_is_not_overridden():
    c=conversation('EN',"Hi, I'm Adrian.")
    criteria=official_checklist().criteria
    criteria[0].description='Operator must state the company name.'
    j=Judgment(criterion_id='contact',value=False,rationale='Company missing.',evidence_turns=[4])
    assert apply_contact_check(c,criteria,[j]) is None
    assert j.value is False


def test_other_violations_do_not_cancel_contact():
    c=conversation('RU','Здравствуйте, я Алексей. Вы вообще читать умеете?')
    assert contact_observation(c)['confirmed']


def test_recheck_preserves_original_appeals_and_other_criteria(settings):
    class BadContact(FakeModel):
        def generate(self,c,criteria,repair=''):
            result=super().generate(c,criteria,repair)
            result['output']['criteria'][0]['value']=False
            return result
    model=BadContact()
    s=Service(settings,model)
    c=source(language='RU') # English opening: positive RU check intentionally does not apply yet.
    s.import_data([c],'dev',1)
    view=s.evaluate(c['conversation_id'])
    id=view['original']['id']
    # Simulate an older, unprocessed valid run for this explicit EN opening.
    row=s.store.get('evaluation',id)
    stored=s.store.get('conversation',c['conversation_id'])
    stored['language']='EN'
    s.store.put('conversation',c['conversation_id'],stored)
    appeal=s.appeal(id,'contact','Check the English greeting.')
    s.decide(appeal['id'],'confirm',None,'Keep this historical decision.',[4],0)
    corrected=s.recheck_contact(id)
    assert corrected['original']['derived_from']==id
    assert corrected['original']['criteria'][0]['value'] is True
    assert corrected['original']['criteria'][1:]==row['criteria'][1:]
    assert s.get_evaluation(id)['original']['criteria'][0]['value'] is False
    assert len(s.get_evaluation(id)['decisions'])==1
    assert model.calls==1 # Recheck used no model call.
    assert s.recheck_contact(id)['original']['id']==corrected['original']['id']
