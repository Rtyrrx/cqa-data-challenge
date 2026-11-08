"""Source-backed positive checks for the unchanged official contact rubric.

This deliberately does not turn an unrecognized opening into a failure. Modified
rubrics and ambiguous speech remain model/human judgments.
"""
import re

from .domain import official_checklist

CONTACT_CHECK_VERSION = 'contact-v2-business-tone'
_NAME = r'(?:[A-ZА-ЯЁӘҒҚҢӨҰҮҺІ][a-zа-яёәғқңөұүһіA-ZА-ЯЁӘҒҚҢӨҰҮҺІ\-\u2019\u0027]+|\[Имя скрыто\])'
_GREETINGS = {
    'EN': re.compile(r'^\s*(hi|hello|good\s+(?:morning|afternoon|evening))\b',re.I),
    'RU': re.compile(r'^\s*(здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)\b',re.I),
    'KZ': re.compile(r'^\s*(сәлеметсіз\s+бе|қайырлы\s+(?:күн|таң|кеш))\b',re.I),
}
_INFORMAL_GREETINGS = {
    'RU': re.compile(r'^\s*(привет(?:ик)?|здравствуй|здорово|салют)\b',re.I),
    'KZ': re.compile(r'^\s*(сәлем|сәлеметсің\s+бе)\b',re.I),
}
_INTRODUCTIONS = {
    'EN': re.compile(r"\b(?i:my name is|i am|i['’]m)\s+(?P<name>"+_NAME+r')'),
    'RU': re.compile(r'\b(?i:меня\s+зовут|мо[её]\s+имя|я)\s+(?P<name>'+_NAME+r')'),
    'KZ': re.compile(r'\b(?i:менің\s+атым|мен)\s+(?P<name>'+_NAME+r')'),
}
_NOT_NAMES = {'here','sorry','happy','ready','checking','looking','glad','your','the','a','support','проверю','проверяю','готов','рада','рад','ваш','ваша','тексеремін'}


def contact_observation(conversation):
    first = next(((i,t) for i,t in enumerate(conversation.transcript,1) if t.speaker=='operator'),None)
    if first is None:
        return {'confirmed':False,'reason':'No operator turn.'}
    index,turn = first
    greeting = _GREETINGS[conversation.language].search(turn.text)
    introduction = _INTRODUCTIONS[conversation.language].search(turn.text)
    informal_pattern = _INFORMAL_GREETINGS.get(conversation.language)
    informal = informal_pattern.search(turn.text) if informal_pattern else None
    confirmed = bool(greeting and introduction and introduction.group('name').casefold() not in _NOT_NAMES)
    return {'confirmed':confirmed,'turn':index,'language':conversation.language,
        'informal_greeting':informal.group(0).strip() if informal else None,
        'greeting':greeting.group(0).strip() if greeting else None,
        'introduction':introduction.group(0) if introduction else None}


def apply_contact_check(conversation,criteria,judgments):
    original_definition = official_checklist().criteria[0]
    criterion = next((c for c in criteria if c.id=='contact'),None)
    if (criterion is None or criterion.description!=original_definition.description
            or criterion.response_type!='boolean' or criterion.allow_na
            or {(type(v),v) for v in criterion.allowed_values}!={(bool,True),(bool,False)}):
        return None
    observation = contact_observation(conversation)
    if not observation['confirmed'] and not observation.get('informal_greeting'):
        return None
    judgment = next(j for j in judgments if j.criterion_id=='contact')
    before = judgment.model_dump()
    judgment.value = observation['confirmed']
    judgment.evidence_turns = [observation['turn']]
    if observation.get('informal_greeting'):
        judgment.rationale = (f'The first operator reply (turn {observation["turn"]}) opens with '
            f'“{observation["informal_greeting"]}”, an informal greeting under the team’s RU/KZ business-tone policy. '
            'A self-introduction does not make this greeting acceptable for contact.')
    else:
        judgment.rationale = (f'The first operator reply (turn {observation["turn"]}) contains the '
            f'{observation["language"]} service greeting “{observation["greeting"]}” and self-introduction '
            f'“{observation["introduction"]}”. Both contact requirements are satisfied.')
    return {'check_version':CONTACT_CHECK_VERSION,'method':'first_reply_business_greeting_and_introduction',
        'observation':observation,'model_judgment_before_check':before}
