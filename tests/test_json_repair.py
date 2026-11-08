import json

import httpx
import pytest

from cqa.domain import Conversation, official_checklist
from cqa.providers import ModelProvider, EvidenceValidationError, output_schema, validate_response_shape, reset_seconds
from cqa.config import Settings
from cqa.store import Store


def test_schema_rejected_then_json_mode_still_checks_exact_schema(tmp_path):
    settings=Settings(db_path=tmp_path/'test.db',provider='groq',model='openai/gpt-oss-120b',api_key='private',request_interval=0)
    transcript=Conversation(conversation_id='test',language='EN',channel='agent chat',transcript=[{'speaker':'operator','timestamp':'00:00','text':'Hello, I am Alex.'}])
    criteria=official_checklist().criteria[:1]
    requests=[]
    def handler(request):
        payload=json.loads(request.content); requests.append(payload)
        if len(requests)==1:
            return httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':'private rejected content'}})
        content={'criteria':{'contact':{'rationale':'The operator greeted and introduced themselves.','evidence_turns':[1],'applicability':'applicable','value':True}},'needs_review':False,'review_reason':''}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}],'usage':{'prompt_tokens':300,'completion_tokens':80}})
    provider=ModelProvider(settings,Store(settings.db_path),httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(EvidenceValidationError):provider.generate(transcript,criteria)
    result=provider.generate(transcript,criteria,repair='Include all required fields.')
    assert requests[0]['response_format']['type']=='json_schema'
    assert requests[1]['response_format']=={'type':'json_object'}
    assert 'exact schema' in requests[1]['messages'][-1]['content']
    assert result['output']['criteria'][0]['value'] is True
    assert 'private rejected content' not in json.dumps(result)


def test_local_json_contract_rejects_missing_facts_wrong_types_and_extra_fields():
    schema=output_schema(official_checklist().criteria,4)
    with pytest.raises(EvidenceValidationError):validate_response_shape({'criteria':{},'needs_review':False,'review_reason':''},schema)
    discovery=schema['properties']['criteria']['properties']['discovery']
    row={'rationale':'The operator clarified missing information.','evidence_turns':[4],'missing_information_at_operator_entry':True,'useful_missing_question_asked':True}
    validate_response_shape(row,discovery)
    for invalid in [{k:v for k,v in row.items() if k!='missing_information_at_operator_entry'}, {**row,'useful_missing_question_asked':'true'}, {**row,'value':True}, {**row,'evidence_turns':[5]}]:
        with pytest.raises(EvidenceValidationError):validate_response_shape(invalid,discovery)


def test_provider_reset_header_units():
    assert reset_seconds('1m2.5s')==62.5
    assert reset_seconds('100ms')==.1
    assert reset_seconds('')==0
