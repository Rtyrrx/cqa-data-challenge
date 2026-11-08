from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, StrictInt

from .config import ROOT, Settings
from .domain import ChecklistInput, StrictModel, Value
from .service import Conflict, Service
from .rubric import with_guidance


class ImportRequest(StrictModel):
    dataset: Literal['dev','prod']
    payload: dict | list | None = None
    group_id: str | None = None
    expected: int | None = Field(default=None,gt=0)


class EvaluationRequest(StrictModel):
    conversation_id: str
    checklist_id: str = 'official-v1'
    force: bool = False


class BatchRequest(StrictModel):
    dataset: Literal['dev','prod']
    checklist_id: str = 'official-v1'
    force: bool = False
    only_unevaluated: bool = False


class AppealRequest(StrictModel):
    evaluation_id: str
    criterion_id: str
    comment: str = Field(min_length=1,max_length=4000)


class DecisionRequest(StrictModel):
    action: Literal['confirm','override']
    value: Value = None
    reason: str = Field(min_length=1,max_length=2000)
    evidence_turns: list[StrictInt] | None = None
    expected_revision: int = Field(ge=0)


class ExportRequest(StrictModel):
    expected: int | None = Field(default=None,gt=0)
    reviewed: bool = False


def create_app(settings=None, provider=None):
    service = Service(settings or Settings.from_env(),provider)

    @asynccontextmanager
    async def lifespan(app):
        for job in service.store.all('job'):
            if job['status'] in ('queued','running'):
                job['status']='interrupted'
                job['error']='Server restarted. Submit a new batch; saved successful evaluations will be reused.'
                service.store.put('job',job['id'],job)
        yield
        if hasattr(service.provider,'close'):
            service.provider.close()

    app = FastAPI(title='CQA Backend Prototype',version='0.1.0',lifespan=lifespan,
        description='Plain local interface, API documentation and CLI. Local demo only; no authentication.')
    app.state.service = service
    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

    @app.get('/',include_in_schema=False)
    def index():
        return FileResponse(ROOT/'static'/'index.html')

    @app.exception_handler(KeyError)
    async def missing(request:Request,exc:KeyError):
        return JSONResponse(status_code=404,content={'detail':str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(request:Request,exc:ValueError):
        return JSONResponse(status_code=409 if isinstance(exc,Conflict) else 400,content={'detail':str(exc)})

    @app.get('/api/health')
    def health():
        s = service.settings
        return {'status':'ok','provider':s.provider,'model':s.model,'model_connection_verified':False,
            'groq_key_configured':bool(s.api_key),'dataset_api_configured':bool(s.dataset_url),'auto_import':s.auto_import,'datasets':service.store.all('dataset'),'usage_last_24h':service.store.usage()}

    @app.post('/api/conversations/import')
    def import_conversations(body:ImportRequest):
        if body.payload is None:
            return service.fetch_dataset(body.dataset,body.group_id,body.expected)
        return service.import_data(body.payload,body.dataset,body.expected)

    @app.get('/api/conversations')
    def conversations(dataset:Literal['dev','prod'] | None=None,language:str | None=None,channel:str | None=None,checklist_id:str='official-v1'):
        allowed = set(service.ensure_dataset(dataset)['conversation_ids']) if dataset else None
        rows = service.store.all('conversation')
        statuses=service.evaluation_statuses(checklist_id)
        return [{'conversation_id':c['conversation_id'],'channel':c['channel'],'language':c['language'],'turn_count':len(c['transcript']),'has_audio':bool(c.get('audio_url')),'evaluation_status':statuses.get(c['conversation_id'],{'status':'not_evaluated'})} for c in rows if (allowed is None or c['conversation_id'] in allowed) and (not language or c['language']==language) and (not channel or c['channel']==channel)]

    @app.post('/api/supplementary-datasets/swap')
    def save_swap():
        return service.save_swap()

    @app.get('/api/supplementary-datasets/swap')
    def swap_status():
        try:
            record=service.store.get('supplementary_dataset','swap')
        except KeyError:
            return {'id':'swap','total':0,'status':'not_loaded'}
        return {k:v for k,v in record.items() if k!='records'}

    @app.get('/api/conversations/{id}')
    def conversation(id:str):
        return service.conversation(id)

    @app.get('/api/checklists')
    def checklists():
        return [with_guidance(c) for c in service.store.all('checklist')]

    @app.get('/api/checklists/{id}')
    def checklist(id:str):
        return with_guidance(service.checklist(id))

    @app.post('/api/checklists',status_code=201)
    def create_checklist(body:ChecklistInput):
        return service.create_checklist(body)

    @app.post('/api/checklists/{id}/versions',status_code=201)
    def version(id:str,body:ChecklistInput):
        return service.create_checklist(body,id)

    @app.post('/api/evaluations')
    def evaluate(body:EvaluationRequest):
        return service.evaluate(**body.model_dump())

    @app.post('/api/evaluations/batch',status_code=202)
    def batch(body:BatchRequest,background:BackgroundTasks):
        job = service.create_job(**body.model_dump())
        background.add_task(service.run_job,job['id'])
        return job

    @app.get('/api/evaluations')
    def evaluations(conversation_id:str | None=None):
        return [e for e in service.store.all('evaluation') if not conversation_id or e['conversation_id']==conversation_id]

    @app.get('/api/evaluations/{id}')
    def evaluation(id:str):
        return service.get_evaluation(id)

    @app.get('/api/jobs/{id}')
    def job(id:str):
        return service.store.get('job',id)

    @app.post('/api/appeals',status_code=201)
    def appeal(body:AppealRequest):
        return service.appeal(**body.model_dump())

    @app.get('/api/appeals')
    def appeals():
        return service.store.all('appeal')

    @app.post('/api/appeals/{id}/decision')
    def decide(id:str,body:DecisionRequest):
        if body.action=='override' and 'value' not in body.model_fields_set:
            raise ValueError('Override requires an explicit value, including null for N/A')
        return service.decide(id,**body.model_dump())

    @app.post('/api/export/{dataset}')
    def export(dataset:Literal['dev','prod'],body:ExportRequest):
        return service.export(dataset,**body.model_dump())

    return app
