import copy
import pytest

from cqa.domain import Conversation, Judgment, calculate_score, official_checklist
from cqa.providers import build_messages, normalize_output
from cqa.rubric import guidance_for, with_guidance
from test_backend import source


def provider_output():
    return {'criteria':{'discovery':{'missing_information_at_operator_entry':False,'useful_missing_question_asked':False,'applicability_reason':'The customer had already supplied the website.','rationale':'No clarification was necessary.','evidence_turns':[1],'quote_turn':1,'evidence_quote':'Where is my tariff?'}},'needs_review':True,'review_reason':'Test.'}


def test_applicability_is_separate_from_satisfaction():
    c=Conversation.model_validate(source())
    output,audit=normalize_output(provider_output(),c,official_checklist().criteria)
    assert output['criteria'][0]['value'] is None
    assert audit['discovery']['applicability']=='not_applicable'


@pytest.mark.parametrize('mutate',[
    lambda p:p['criteria']['discovery'].update(evidence_quote='Client disconnected abruptly'),
    lambda p:p['criteria']['discovery'].update(quote_turn=99),
    lambda p:p['criteria']['discovery'].update(evidence_turns=[4]),
    lambda p:p['criteria']['discovery'].update(missing_information_at_operator_entry='unknown'),
])
def test_unverifiable_evidence_rejected(mutate):
    p=provider_output(); mutate(p)
    with pytest.raises(ValueError):normalize_output(p,Conversation.model_validate(source()),official_checklist().criteria)


def test_no_na_escape_for_contact():
    p=provider_output();p['criteria']['contact']=p['criteria'].pop('discovery')
    p['criteria']['contact'].pop('missing_information_at_operator_entry')
    p['criteria']['contact'].pop('useful_missing_question_asked')
    p['criteria']['contact'].update(applicability='not_applicable',value=False)
    with pytest.raises(ValueError):normalize_output(p,Conversation.model_validate(source()),official_checklist().criteria)


def test_source_quotes_are_retrieved_without_model_copying():
    p=provider_output()
    p['criteria']['discovery'].pop('evidence_quote')
    p['criteria']['discovery'].pop('quote_turn')
    p['criteria']['discovery'].pop('applicability_reason')
    output,audit=normalize_output(p,Conversation.model_validate(source()),official_checklist().criteria)
    assert audit['discovery']['evidence_quote']==source()['transcript'][0]['text']
    assert output['criteria'][0]['value'] is None


def test_positive_operator_behavior_cannot_be_proved_by_client_alone():
    p=provider_output()
    p['criteria']['discovery'].update(missing_information_at_operator_entry=True,useful_missing_question_asked=True)
    with pytest.raises(ValueError):normalize_output(p,Conversation.model_validate(source()),official_checklist().criteria)


def test_custom_rubric_is_not_replaced():
    c=official_checklist().criteria[1]
    assert 'INCLUDING client/bot context' in guidance_for(c)
    c.description='Evaluate whether the operator offers an optional service.'
    assert guidance_for(c)==''


def test_guidance_is_visible_and_sent_to_model_without_mutating_checklist():
    checklist=official_checklist().model_dump()
    before=copy.deepcopy(checklist)
    rendered=with_guidance(checklist)
    assert 'transcript simply ending is NOT evidence' in rendered['evaluation_guidance']['closure']
    assert checklist==before
    messages=build_messages(Conversation.model_validate(source()),official_checklist().criteria)
    assert 'decision_guidance' in messages[1]['content']
    assert 'test-1' not in messages[1]['content'] # No conversation-ID-based expected answers.


def test_problem_case_and_good_case_do_not_use_blanket_score_penalty():
    values={'contact':False,'discovery':None,'identification':None,'consultation':20,'empathy':False,'dialogue':7,'closure':False,'critical':False}
    j=[Judgment(criterion_id=id,value=v,rationale='Human-reviewed development expectation.',evidence_turns=[1]) for id,v in values.items()]
    assert calculate_score(official_checklist().criteria,j)[0]['final_score']==46.92
    for row in j:
        if row.criterion_id=='contact':row.value=True
        if row.criterion_id=='empathy':row.value=True
        if row.criterion_id=='dialogue':row.value=10
        if row.criterion_id=='closure':row.value=True
    assert calculate_score(official_checklist().criteria,j)[0]['final_score']==100
