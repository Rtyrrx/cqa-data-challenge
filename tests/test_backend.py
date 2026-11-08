import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cqa.api import create_app
from cqa.config import Settings
from cqa.domain import ChecklistInput, Conversation, Judgment, ModelOutput, calculate_score, official_checklist, validate_judgments
from cqa.providers import ModelProvider, ProviderError, output_schema
from cqa.service import Conflict, Service, validate_submission, write_json
from cqa.store import Store


def source(id='test-1',language='RU'):
    return {'conversation_id':id,'channel':'agent chat','language':language,'audio_url':None,'transcript':[
        {'timestamp':'00:00','speaker':'client','text':'Where is my tariff?'},
        {'timestamp':'00:01','speaker':'bot','text':'Connecting.'},
        {'timestamp':'00:02','speaker':'system','text':'Operator connected.'},
        {'timestamp':'00:03','speaker':'operator','text':'Hello, I am Alex. Open Profile. Anything else? Goodbye.'},
    ]}


def test_fbroker_and_swap_remain_separate(settings,monkeypatch):
    settings.dataset_url='https://example.invalid/api?sig=private'
    def fetch(url,**kwargs):
        group=url.params['group_id']
        records=[source(f'{group}-{i}') for i in range(10 if group=='FBroker' else 3)]
        return httpx.Response(200,json={'isSuccess':True,'data':{'dataset_group_id':group,'total_records':len(records),'records':records}},request=httpx.Request('GET',url))
    monkeypatch.setattr('cqa.service.httpx.get',fetch)
    model=FakeModel()
    with TestClient(create_app(settings,model)) as client:
        assert client.post('/api/conversations/import',json={'dataset':'prod','expected':10}).json()['source_group_id']=='FBroker'
        assert client.get('/api/supplementary-datasets/swap').json()['status']=='not_loaded'
        assert client.post('/api/supplementary-datasets/swap').json()['total']==3
        assert client.post('/api/supplementary-datasets/swap').json()['status']=='saved_not_evaluated'
        assert client.get('/api/supplementary-datasets/swap').json()['total']==3
        assert len(client.get('/api/conversations?dataset=prod').json())==10
        assert len(client.get('/api/conversations').json())==10
        assert client.get('/api/conversations/Swap-0').status_code==404
        assert client.post('/api/conversations/import',json={'dataset':'prod','group_id':'Swap'}).status_code==400
        assert model.calls==0


def test_swap_validation_retains_saved_source(settings):
    service=Service(settings,FakeModel())
    payload={'isSuccess':True,'data':{'dataset_group_id':'Swap','total_records':1,'records':[source()]}}
    service.save_swap(payload)
    changed=copy.deepcopy(payload)
    changed['data']['records'][0]['transcript'][0]['text']='Changed'
    with pytest.raises(Conflict):service.save_swap(changed)
    with pytest.raises(ValueError):service.import_data(payload,'prod',1)
    payload['data']['total_records']=2
    with pytest.raises(ValueError):service.save_swap(payload)
    assert service.store.all('conversation')==[]


def test_schema_rejection_requests_repair_without_leaking_provider_text(settings):
    settings.provider='groq'; settings.api_key='test'
    client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':'private source text'}})))
    provider=ModelProvider(settings,Store(settings.db_path),client)
    with pytest.raises(ValueError,match='required field') as error:
        provider.generate(Conversation.model_validate(source()),official_checklist().criteria)
    assert 'private source text' not in str(error.value)


def test_dataset_api_auto_load_cache_and_preserve_history(settings,monkeypatch):
    settings.dataset_url='https://example.invalid/dataset?sig=test-private-signature'
    calls=[]
    records=[source(f'auto-{i}') for i in range(65)]
    def fetch(url,**kwargs):
        assert url.params['group_id']=='DEV'
        calls.append(url)
        return httpx.Response(200,json={'isSuccess':True,'data':{'records':records,'total_records':65,'dataset_group_id':'DEV'}},request=httpx.Request('GET',url))
    monkeypatch.setattr('cqa.service.httpx.get',fetch)
    model=FakeModel()
    with TestClient(create_app(settings,model)) as client:
        assert len(client.get('/api/conversations?dataset=dev').json())==65
        assert len(client.get('/api/conversations?dataset=dev').json())==65
        assert len(calls)==1 and model.calls==0
        result=client.post('/api/evaluations',json={'conversation_id':'auto-0'}).json()
        evaluation_id=result['original']['id']
        assert client.post('/api/conversations/import',json={'dataset':'dev','expected':65}).status_code==200
        assert client.get('/api/evaluations/'+evaluation_id).json()['original']==result['original']
        assert model.calls==1 and len(calls)==2
        records[0]['transcript'][0]['text']='Changed upstream source'
        assert client.post('/api/conversations/import',json={'dataset':'dev','expected':65}).status_code==409
        assert client.get('/api/conversations/auto-0').json()['transcript'][0]['text']=='Where is my tariff?'


def test_dataset_api_missing_configuration_is_visible(settings):
    with TestClient(create_app(settings,FakeModel())) as client:
        response=client.get('/api/conversations?dataset=dev')
        assert response.status_code==400
        assert 'CQA_DATASET_URL' in response.json()['detail']
        assert client.get('/api/health').json()['datasets']==[]


def test_dataset_api_failure_is_retryable_and_hides_url(settings,monkeypatch):
    settings.dataset_url='https://example.invalid/dataset?sig=private-do-not-expose'
    calls=[]
    def fetch(url,**kwargs):
        calls.append(url)
        return httpx.Response(403 if len(calls)==1 else 200,json=[source(f'auto-{i}') for i in range(65)],request=httpx.Request('GET',url))
    monkeypatch.setattr('cqa.service.httpx.get',fetch)
    with TestClient(create_app(settings,FakeModel())) as client:
        response=client.get('/api/conversations?dataset=dev')
        assert response.status_code==400 and '403' in response.json()['detail']
        assert 'private-do-not-expose' not in response.text
        assert client.get('/api/health').json()['datasets']==[]
        assert len(client.get('/api/conversations?dataset=dev').json())==65


def test_dataset_api_auto_import_can_be_disabled(settings,monkeypatch):
    settings.dataset_url='https://example.invalid/dataset'
    settings.auto_import=False
    monkeypatch.setattr('cqa.service.httpx.get',lambda *a,**k:pytest.fail('Auto import disabled'))
    with TestClient(create_app(settings,FakeModel())) as client:
        assert client.get('/api/conversations?dataset=dev').status_code==400
        assert client.get('/api/conversations?dataset=prod').status_code==400


def judgments(criteria=None):
    return [Judgment(criterion_id=c.id,value=False if c.response_type=='flag' else True if c.response_type=='boolean' else max(v for v in c.allowed_values if type(v) is int),rationale='Grounded test judgment.',evidence_turns=[4]) for c in criteria or official_checklist().criteria]


class FakeModel:
    """Test injection only; there is deliberately no fake mode in production config."""
    def __init__(self,fail=False):
        self.calls = 0
        self.fail = fail
        self.seen = []

    def generate(self,conversation,criteria,repair=''):
        self.calls += 1
        self.seen.append([c.model_dump() for c in criteria])
        if self.fail:
            raise ProviderError('Simulated unavailable provider')
        return {'output':{'criteria':[j.model_dump() for j in judgments(criteria)],'needs_review':False,'review_reason':''},'usage':{'input_tokens':100,'output_tokens':100}}

    def close(self):
        pass


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path/'test.sqlite3',request_interval=0,max_attempts=1)


@pytest.fixture
def service(settings):
    s = Service(settings,FakeModel())
    s.import_data([source()],'dev',1)
    return s


def test_scoring_na_scaling_and_critical():
    criteria = official_checklist().criteria
    j = judgments()
    assert calculate_score(criteria,j)[0]['final_score']==100
    by_id = {x.criterion_id:x for x in j}
    by_id['identification'].value = None
    by_id['dialogue'].value = 7
    by_id['critical'].value = True
    score,details = calculate_score(criteria,j)
    assert score=={'final_score':94.38,'critical_flag':True}
    assert next(x for x in details if x['criterion_id']=='dialogue')['earned_before_normalization']==10.5
    for x in j:
        if x.value is not None:
            x.value = False if type(x.value) is bool else 0
    assert calculate_score(criteria,j)[0]['final_score']==0


@pytest.mark.parametrize('id,value',[('contact',None),('consultation',17),('dialogue',8),('dialogue',True),('contact',1)])
def test_invalid_values_rejected(id,value):
    j = judgments()
    next(x for x in j if x.criterion_id==id).value=value
    with pytest.raises(ValueError):
        validate_judgments(official_checklist().criteria,j,4)


@pytest.mark.parametrize('turns',[[0],[5],[True],[],[4,4]])
def test_evidence_indices_and_types(turns):
    raw = [x.model_dump() for x in judgments()]
    raw[0]['evidence_turns']=turns
    with pytest.raises((ValueError,ValidationError)):
        j = [Judgment.model_validate(x) for x in raw]
        validate_judgments(official_checklist().criteria,j,4)


def test_duplicate_criterion_and_bad_definition():
    criteria = official_checklist().criteria
    j = judgments()
    j[-1] = j[0]
    with pytest.raises(ValueError):
        validate_judgments(criteria,j,4)
    raw = official_checklist().model_dump()
    raw['criteria'][0]['allowed_values']=[True,False,None]
    with pytest.raises(ValidationError):
        ChecklistInput.model_validate(raw)


def test_import_is_atomic_and_sources_are_immutable(settings):
    s = Service(settings,FakeModel())
    s.import_data([source()],'dev',1)
    changed=source()
    changed['transcript'][0]['text']='changed'
    with pytest.raises(Conflict):
        s.import_data([source('new'),changed],'prod',2)
    assert len(s.store.all('conversation'))==1
    with pytest.raises(KeyError):
        s.store.get('dataset','prod')
    with pytest.raises(ValueError):
        s.import_data([source(),source()],'dev')


def test_full_workflow_versions_cache_appeal_export_persistence(service,settings):
    result = service.evaluate('test-1')
    id = result['original']['id']
    assert result['original']['score']['final_score']==100
    assert service.evaluate('test-1')['cached']
    assert service.provider.calls==1
    appeal=service.appeal(id,'dialogue','This answer was unclear.')
    view=service.decide(appeal['id'],'override',4,'Customer needs to ask again.',[4],0)
    assert view['original']['score']['final_score']==100
    assert view['final']['score']['final_score']==91
    with pytest.raises(Conflict):
        service.decide(appeal['id'],'override',7,'Another decision.',[4],0)
    assert Service(settings,FakeModel()).get_evaluation(id)['final']['score']['final_score']==91
    raw = service.export('dev',1)
    reviewed=service.export('dev',1,reviewed=True)
    assert raw['results'][0]['score']['final_score']==100
    assert reviewed['results'][0]['score']['final_score']==91
    assert set(raw['results'][0])=={'conversation_id','status','criteria','score'}
    definition=official_checklist()
    definition.criteria[0].description='Check whether the operator names the company.'
    definition.criteria[0].id='company_name'
    checklist=service.create_checklist(definition,'official-v1')
    new=service.evaluate('test-1',checklist['id'])
    assert not new['cached']
    assert service.provider.seen[-1][0]['id']=='company_name'
    assert service.checklist('official-v1')['criteria'][0]['id']=='contact'
    assert service.export('dev',1)['results'][0]['criteria'][0]['criterion_id']=='contact'


def test_confirm_and_stale_other_appeal(service):
    id=service.evaluate('test-1')['original']['id']
    first=service.appeal(id,'dialogue','Review one.')
    second=service.appeal(id,'empathy','Review two.')
    assert service.decide(first['id'],'confirm',None,'Confirmed after review.',None,0)['revision']==1
    with pytest.raises(Conflict):
        service.decide(second['id'],'confirm',None,'Confirmed.',None,0)
    assert service.decide(second['id'],'confirm',None,'Confirmed.',None,1)['revision']==2


def test_failed_evaluation_batch_and_export(settings):
    s=Service(settings,FakeModel(fail=True))
    s.import_data([source('one'),source('two')],'dev',2)
    job=s.create_job('dev')
    finished=s.run_job(job['id'])
    assert finished['status']=='complete_with_errors'
    payload=s.export('dev',2)
    assert all(r['status']=='error' and r['criteria']==[] and r['score'] is None for r in payload['results'])
    s.provider=FakeModel()
    finished=s.run_job(s.create_job('dev')['id'])
    assert finished['status']=='complete'
    assert s.provider.calls==2
    assert all(i['cached'] for i in s.run_job(s.create_job('dev')['id'])['items'])


def test_unattempted_export_and_id_checks(service):
    with pytest.raises(ValueError):
        service.export('dev',1)
    service.evaluate('test-1')
    payload=service.export('dev',1)
    payload['results'][0]['conversation_id']='wrong'
    with pytest.raises(ValueError):
        validate_submission(payload,{'test-1':service.conversation('test-1')},1)


def test_forged_score_and_extra_fields(service):
    service.evaluate('test-1')
    payload=service.export('dev',1)
    payload['results'][0]['score']['final_score']=99
    with pytest.raises(ValueError):
        validate_submission(payload,{'test-1':service.conversation('test-1')},1)
    payload=service.export('dev',1)
    payload['results'][0]['debug']='unofficial'
    with pytest.raises(ValueError):
        validate_submission(payload,{'test-1':service.conversation('test-1')},1)


def test_groq_payload_transport_usage_and_no_key_leak(settings):
    settings.provider='groq'
    settings.model='openai/gpt-oss-120b'
    settings.api_key='test-secret'
    store=Store(settings.db_path)
    seen=[]
    def handler(request):
        seen.append(json.loads(request.content))
        by_id={j.criterion_id:{**j.model_dump(exclude={'criterion_id'}),'applicability':'applicable'} for j in judgments()}
        facts={'discovery':{'missing_information_at_operator_entry':True,'useful_missing_question_asked':True},
            'identification':{'protected_data_or_action_requested':True,'verification_confirmed_before_action':True},
            'consultation':{'customer_request_formulated':True},
            'closure':{'opportunity_lost':False,'operator_summary_or_help_offer_present':True,'operator_farewell_present':True}}
        for id,fields in facts.items():
            by_id[id].pop('applicability')
            if id!='consultation':by_id[id].pop('value')
            by_id[id].update(fields)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'criteria':by_id,'needs_review':False,'review_reason':''})}}],'usage':{'prompt_tokens':150,'completion_tokens':250}})
    provider=ModelProvider(settings,store,httpx.Client(transport=httpx.MockTransport(handler)))
    result=provider.generate(Conversation.model_validate(source()),official_checklist().criteria)
    assert seen[0]['response_format']['json_schema']['strict'] is True
    assert seen[0]['reasoning_effort']=='low'
    assert result['usage']['output_tokens']==250
    assert len(ModelOutput.model_validate(result['output']).criteria)==8
    schema=seen[0]['response_format']['json_schema']['schema']['properties']['criteria']
    assert set(schema['required'])=={c.id for c in official_checklist().criteria}
    assert store.usage()[0]['input_tokens']==150
    assert 'test-secret' not in json.dumps(result)


def test_ollama_payload_and_context_guard(settings):
    settings.evaluation_strategy='single'
    settings.ollama_context=32768
    seen=[]
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'done':True,'done_reason':'stop','message':{'content':'{"criteria":{},"needs_review":true,"review_reason":"test"}'},'prompt_eval_count':300,'eval_count':100})
    provider=ModelProvider(settings,Store(settings.db_path),httpx.Client(transport=httpx.MockTransport(handler)))
    provider.generate(Conversation.model_validate(source()),official_checklist().criteria)
    assert seen[0]['think'] is False
    assert seen[0]['format']['type']=='object'
    settings.ollama_context=100
    with pytest.raises(ProviderError,match='not truncated'):
        provider.generate(Conversation.model_validate(source()),official_checklist().criteria)


@pytest.mark.parametrize('status',[401,429,500])
def test_provider_failure_is_safe_and_not_a_score(settings,status):
    settings.provider='groq'
    settings.api_key='secret-do-not-print'
    provider=ModelProvider(settings,Store(settings.db_path),httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,json={'error':'secret-do-not-print'},headers={'retry-after':'2'}))))
    with pytest.raises(ProviderError) as caught:
        provider.generate(Conversation.model_validate(source()),official_checklist().criteria)
    assert 'secret-do-not-print' not in str(caught.value)
    assert caught.value.retryable==(status!=401)


def test_budget_guard_blocks_before_request(settings):
    settings.provider='groq'
    settings.api_key='test'
    settings.token_budget=1
    provider=ModelProvider(settings,Store(settings.db_path),httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('Should not call provider'))))
    with pytest.raises(ProviderError,match='budget'):
        provider.generate(Conversation.model_validate(source()),official_checklist().criteria)


def test_api_end_to_end_without_interface(settings):
    with TestClient(create_app(settings,FakeModel())) as client:
        assert client.get('/').status_code==200
        assert 'CQA' in client.get('/').text
        assert client.get('/static/app.js').status_code==200
        assert client.get('/api/health').status_code==200
        assert client.post('/api/conversations/import',json={'dataset':'dev','payload':[source()],'expected':1}).status_code==200
        assert client.get('/api/conversations?dataset=dev').json()[0]['turn_count']==4
        view=client.post('/api/evaluations',json={'conversation_id':'test-1'}).json()
        id=view['original']['id']
        appeal=client.post('/api/appeals',json={'evaluation_id':id,'criterion_id':'dialogue','comment':'Review.'}).json()
        decision=client.post('/api/appeals/'+appeal['id']+'/decision',json={'action':'override','value':7,'reason':'One lapse.','evidence_turns':[4],'expected_revision':0})
        assert decision.status_code==200
        assert decision.json()['final']['score']['final_score']==95.5
        assert client.post('/api/appeals/'+appeal['id']+'/decision',json={'action':'confirm','reason':'Again.','expected_revision':0}).status_code==409
        assert client.post('/api/export/dev',json={'expected':1}).json()['results'][0]['score']['final_score']==100
        assert client.post('/api/export/dev',json={'expected':1,'reviewed':True}).json()['results'][0]['score']['final_score']==95.5
        assert client.get('/api/evaluations/missing').status_code==404
        job=client.post('/api/evaluations/batch',json={'dataset':'dev'}).json()
        assert client.get('/api/jobs/'+job['id']).json()['status']=='complete'


def test_repair_invalid_model_output_once(settings):
    settings.max_attempts=3
    class RepairModel(FakeModel):
        def generate(self,conversation,criteria,repair=''):
            result=super().generate(conversation,criteria,repair)
            if self.calls==1:
                result['output']['criteria'][0]['evidence_turns']=[999]
            else:
                assert repair
            return result
    model=RepairModel()
    s=Service(settings,model)
    s.import_data([source()],'dev',1)
    result=s.evaluate('test-1')['original']
    assert result['status']=='ok' and result['attempts']==2
    assert result['usage']['input_tokens']==200


def test_atomic_json_write_unicode(tmp_path):
    path=tmp_path/'result.json'
    write_json(path,{'text':'Сәлеметсіз бе'})
    assert json.loads(path.read_text(encoding='utf-8'))['text']=='Сәлеметсіз бе'
    assert not path.with_suffix('.json.tmp').exists()


def test_pending_batch_skips_success_retries_errors_and_blocks_duplicate(settings):
    model=FakeModel()
    s=Service(settings,model)
    s.import_data([source('done'),source('failed'),source('new')],'dev',3)
    s.evaluate('done')
    model.fail=True
    s.evaluate('failed')
    model.fail=False
    assert s.evaluation_statuses()['done']['status']=='evaluated'
    assert s.evaluation_statuses()['failed']['status']=='error'
    job=s.create_job('dev',only_unevaluated=True)
    assert job['conversation_ids']==['failed','new']
    assert s.evaluation_statuses()['new']['status']=='queued'
    with pytest.raises(Conflict):s.create_job('dev',only_unevaluated=True)
    with pytest.raises(ValueError):s.create_job('dev',only_unevaluated=True,force=True)
    s.run_job(job['id'])
    assert model.calls==4
    assert all(v['status']=='evaluated' for v in s.evaluation_statuses().values())
    assert s.create_job('dev',only_unevaluated=True)['conversation_ids']==[]


def test_status_preserves_success_after_failed_rerun_and_separates_checklists(settings):
    model=FakeModel()
    with TestClient(create_app(settings,model)) as client:
        client.post('/api/conversations/import',json={'dataset':'dev','payload':[source()],'expected':1})
        assert client.get('/api/conversations?dataset=dev').json()[0]['evaluation_status']['status']=='not_evaluated'
        client.post('/api/evaluations',json={'conversation_id':'test-1'})
        model.fail=True
        client.post('/api/evaluations',json={'conversation_id':'test-1','force':True})
        assert client.get('/api/conversations?dataset=dev').json()[0]['evaluation_status']['status']=='evaluated'
        service=client.app.state.service
        custom=service.create_checklist(official_checklist())
        assert client.get('/api/conversations',params={'dataset':'dev','checklist_id':custom['id']}).json()[0]['evaluation_status']['status']=='not_evaluated'
        job=client.post('/api/evaluations/batch',json={'dataset':'dev','only_unevaluated':True}).json()
        assert job['conversation_ids']==[]
