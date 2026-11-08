import json
import httpx
import pytest

from cqa.domain import Conversation, official_checklist
from cqa.providers import ModelProvider, normalize_output, output_schema
from cqa.store import Store
from test_backend import source, settings


@pytest.mark.parametrize('id,facts,expected',[
    ('discovery',{'missing_information_at_operator_entry':False,'useful_missing_question_asked':False},None),
    ('discovery',{'missing_information_at_operator_entry':True,'useful_missing_question_asked':False},False),
    ('identification',{'protected_data_or_action_requested':False,'verification_confirmed_before_action':False},None),
    ('identification',{'protected_data_or_action_requested':True,'verification_confirmed_before_action':False},False),
    ('closure',{'opportunity_lost':False,'operator_summary_or_help_offer_present':False,'operator_farewell_present':False},False),
    ('closure',{'opportunity_lost':False,'operator_summary_or_help_offer_present':True,'operator_farewell_present':False},False),
    ('closure',{'opportunity_lost':False,'operator_summary_or_help_offer_present':True,'operator_farewell_present':True},True),
    ('closure',{'opportunity_lost':True,'operator_summary_or_help_offer_present':False,'operator_farewell_present':False},None),
])
def test_facts_derive_values_without_confusing_na_with_failure(id,facts,expected):
    c=Conversation.model_validate(source())
    item={'rationale':'Source-based test facts.','evidence_turns':[4],**facts}
    parsed,audit=normalize_output({'criteria':{id:item},'needs_review':False,'review_reason':''},c,official_checklist().criteria)
    assert parsed['criteria'][0]['value'] is expected
    assert audit[id]['decision_facts']==facts


def test_local_focused_requests_resume_and_keep_other_criteria(settings):
    calls=[]
    def handler(request):
        body=json.loads(request.content)
        ids=list(body['format']['properties']['criteria']['properties'])
        assert len(ids)==1
        id=ids[0];calls.append(id)
        item={'rationale':'Actual source checked.','evidence_turns':[4]}
        if id=='discovery':item.update(missing_information_at_operator_entry=False,useful_missing_question_asked=False)
        elif id=='identification':item.update(protected_data_or_action_requested=False,verification_confirmed_before_action=False)
        elif id=='consultation':item.update(customer_request_formulated=True,value=20)
        elif id=='closure':item.update(opportunity_lost=False,operator_summary_or_help_offer_present=True,operator_farewell_present=True)
        else:item.update(applicability='applicable',value=False if id=='critical' else 10 if id=='dialogue' else True)
        return httpx.Response(200,json={'done':True,'done_reason':'stop','message':{'content':json.dumps({'criteria':{id:item},'needs_review':False,'review_reason':''})},'prompt_eval_count':30,'eval_count':20})
    provider=ModelProvider(settings,Store(settings.db_path),httpx.Client(transport=httpx.MockTransport(handler)))
    c=Conversation.model_validate(source())
    first=provider.generate(c,official_checklist().criteria)
    assert len(calls)==8 and len(first['output']['criteria'])==8
    assert first['usage']['input_tokens']==240
    second=provider.generate(c,official_checklist().criteria)
    assert len(calls)==8 and second['usage']=={'input_tokens':0,'output_tokens':0}


def test_focused_schema_does_not_ask_for_a_grade_before_reasoning():
    criteria=official_checklist().criteria
    schema=output_schema(criteria,10)['properties']['criteria']['properties']
    assert list(schema['identification']['properties'])[:2]==['rationale','evidence_turns']
    assert 'value' not in schema['identification']['properties']
    assert 'protected_data_or_action_requested' in schema['identification']['required']
