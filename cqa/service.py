import copy
import json
import time
from pathlib import Path
from threading import Lock

import httpx
from pydantic import ValidationError

from .domain import ChecklistInput, Conversation, Criterion, Judgment, ModelOutput, calculate_score, official_checklist, validate_judgments
from .providers import PROMPT_VERSION, ModelProvider, ProviderError
from .store import Store, dump, fingerprint, now, uid
from .contact import CONTACT_CHECK_VERSION, apply_contact_check
from .tone import TONE_POLICY_VERSION, tone_observations
from .rubric import RUBRIC_VERSION
from .source_checks import SOURCE_CHECK_VERSION, apply_source_checks


class Conflict(ValueError):
    pass


class Service:
    def __init__(self, settings, provider=None):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.provider = provider or ModelProvider(settings,self.store)
        self.evaluation_lock = Lock()
        self.import_lock = Lock()
        try:
            self.store.get('checklist','official-v1')
        except KeyError:
            self.store.put('checklist','official-v1',{'id':'official-v1', 'parent_id':None,'created_at':now(),**official_checklist().model_dump()})

    def checklist(self,id):
        return self.store.get('checklist',id)

    def create_checklist(self, definition: ChecklistInput, parent_id=None):
        if parent_id:
            self.checklist(parent_id)
        id = uid('checklist')
        payload = {'id':id,'parent_id':parent_id,'created_at':now(),**definition.model_dump()}
        self.store.put('checklist',id,payload)
        return payload

    def import_data(self, payload, dataset, expected=None):
        if dataset not in ('dev','prod'):
            raise ValueError('Dataset must be dev or prod')
        if isinstance(payload,dict) and 'isSuccess' in payload:
            if payload['isSuccess'] is not True:
                raise ValueError('Organizer API did not return success')
            data = payload.get('data',{})
            records = data.get('records')
            group = data.get('dataset_group_id','')
            total = data.get('total_records')
        else:
            records = payload.get('records') if isinstance(payload,dict) else payload
            group, total = '',None
        if str(group).casefold()=='swap':
            raise ValueError('SWAP must be saved separately; evaluation is not enabled for this set.')
        if not isinstance(records,list) or not records:
            raise ValueError('Expected a nonempty records array or organizer response')
        conversations = [Conversation.model_validate(r) for r in records]
        ids = [c.conversation_id for c in conversations]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate conversation IDs in dataset')
        if total is not None and (type(total) is not int or total != len(ids)):
            raise ValueError('API total_records does not match records')
        if expected is not None and len(ids) != expected:
            raise ValueError(f'Expected {expected} records, received {len(ids)}')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for c in conversations:
                try:
                    old = self.store.get('conversation',c.conversation_id,db)
                except KeyError:
                    old = None
                if old and fingerprint({k:v for k,v in old.items() if k!='audio_url'}) != fingerprint(c.model_dump(exclude={'audio_url'})):
                    raise Conflict('A conversation ID already exists with different source turns; import rejected')
                self.store.put('conversation',c.conversation_id,c.model_dump(),db)
            try:
                previous = self.store.get('dataset',dataset,db)
            except KeyError:
                previous = None
            if previous and set(previous['conversation_ids']) != set(ids):
                raise Conflict('Dataset is already bound to different IDs; use a separate database for a different set')
            self.store.put('dataset',dataset,{'id':dataset,'source_group_id':group,'conversation_ids':ids,'imported_at':now()},db)
        return {'dataset':dataset,'total':len(ids),'source_group_id':group}

    def ensure_dataset(self, dataset):
        # The first UI request imports missing DEV data. Recheck under the lock
        # so concurrent browser requests do not each download the same dataset.
        with self.import_lock:
            try:
                existing = self.store.get('dataset',dataset)
                if existing.get('conversation_ids'):
                    return existing
            except KeyError:
                pass
            if dataset != 'dev' or not self.settings.auto_import:
                raise ValueError('Набор не загружен. Откройте «Данные» и загрузите его через API или JSON.')
            self.fetch_dataset('dev',self.settings.dataset_group_id,65)
            return self.store.get('dataset','dev')

    def fetch_dataset(self, dataset, group_id=None, expected=None):
        if dataset not in ('dev','prod'):
            raise ValueError('Dataset must be dev or prod')
        group_id=group_id or (self.settings.dataset_group_id if dataset=='dev' else 'FBroker')
        if group_id.casefold()=='swap':
            raise ValueError('Use the separate SWAP download, without evaluation.')
        return self.import_data(self._fetch_payload(group_id),dataset,expected)

    def save_swap(self, payload=None):
        payload=self._fetch_payload('Swap') if payload is None else payload
        data=payload.get('data',{}) if isinstance(payload,dict) else {}
        if not isinstance(payload,dict) or not isinstance(data,dict) or payload.get('isSuccess') is not True or str(data.get('dataset_group_id','')).casefold()!='swap':
            raise ValueError('Expected the successful organizer SWAP response')
        records=data.get('records')
        if not isinstance(records,list) or not records:
            raise ValueError('Expected nonempty SWAP records')
        records=[Conversation.model_validate(c).model_dump() for c in records]
        ids=[c['conversation_id'] for c in records]
        if len(set(ids))!=len(ids) or type(data.get('total_records')) is not int or data['total_records']!=len(ids):
            raise ValueError('SWAP record count or IDs are invalid')
        record={'id':'swap','source_group_id':'Swap','records':records,'total':len(ids),'saved_at':now(),'status':'saved_not_evaluated'}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                previous=self.store.get('supplementary_dataset','swap',db)
            except KeyError:
                previous=None
            if previous and fingerprint(previous['records'])!=fingerprint(records):
                raise Conflict('Saved SWAP differs from the received source; existing data retained')
            self.store.put('supplementary_dataset','swap',record,db)
        return {k:v for k,v in record.items() if k!='records'}

    def _fetch_payload(self, group_id):
        if not self.settings.dataset_url:
            raise ValueError('Не указан адрес API организаторов. Настройте CQA_DATASET_URL в .env и перезапустите сервер либо загрузите JSON.')
        try:
            url = httpx.URL(self.settings.dataset_url)
            if group_id:
                url = url.copy_set_param('group_id',group_id)
            response = httpx.get(url,timeout=60,follow_redirects=False)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            raise ValueError(f'API организаторов вернул HTTP {error.response.status_code}. Проверьте доступ к ссылке и ID группы.') from None
        except httpx.TimeoutException:
            raise ValueError('API организаторов не ответил за 60 секунд. Повторите загрузку позже.') from None
        except (httpx.HTTPError,ValueError):
            raise ValueError('Dataset fetch failed. Check configured URL, group ID and network; URL was not logged.') from None
        return payload

    def conversation(self,id):
        return Conversation.model_validate(self.store.get('conversation',id))

    def evaluate(self, conversation_id, checklist_id='official-v1', force=False):
        # A single model queue avoids racing quota guards and duplicate expensive calls.
        with self.evaluation_lock:
            return self._evaluate(conversation_id,checklist_id,force)

    def _evaluate(self, conversation_id, checklist_id, force):
        conversation = self.conversation(conversation_id)
        checklist = self.checklist(checklist_id)
        criteria = [Criterion.model_validate(c) for c in checklist['criteria']]
        s = self.settings
        metadata = {'provider':s.provider,'name':s.model,'prompt_version':PROMPT_VERSION,
            'contact_check_version':CONTACT_CHECK_VERSION,
            'tone_policy_version':TONE_POLICY_VERSION,
            'rubric_guidance_version':RUBRIC_VERSION,
            'evaluation_strategy':s.evaluation_strategy,
            'source_check_version':SOURCE_CHECK_VERSION,
            'max_output_tokens':s.max_output_tokens,'ollama_context':s.ollama_context,
            'reasoning':'disabled' if s.provider=='ollama' or 'qwen' in s.model else 'low',
            'require_review':s.require_review}
        key = fingerprint({'source':conversation.model_dump(exclude={'audio_url'}),'checklist':checklist,'model':metadata})
        if not force:
            cached = [e for e in self.store.all('evaluation') if e['cache_key']==key and e['status']=='ok']
            if cached:
                return {**self.get_evaluation(cached[-1]['id']),'cached':True}
        evaluation = {'id':uid('evaluation'),'conversation_id':conversation_id,'checklist_version_id':checklist_id,
            'created_at':now(),'model_metadata':metadata,'cache_key':key,'criteria':[],'score':None,
            'status':'error','error':'Evaluation did not complete','attempts':0,'usage':{'input_tokens':0,'output_tokens':0}}
        self.store.put('evaluation',evaluation['id'],evaluation)
        started = time.monotonic()
        repair = ''
        repair_used = False
        for attempt in range(s.max_attempts):
            evaluation['attempts'] += 1
            try:
                if not any(t.speaker=='operator' for t in conversation.transcript):
                    raise ProviderError('No operator turns are available for evaluation.')
                result = self.provider.generate(conversation,criteria,repair)
                for field in evaluation['usage']:
                    evaluation['usage'][field] += result['usage'].get(field,0)
                output = ModelOutput.model_validate(result['output'])
                evaluation['evidence_audit'] = result.get('audit',{})
                validate_judgments(criteria,output.criteria,len(conversation.transcript))
                diagnostic = apply_contact_check(conversation,criteria,output.criteria)
                if diagnostic:
                    diagnostic['model_evidence_audit_before_check']=copy.deepcopy(evaluation['evidence_audit'].get('contact'))
                    evaluation['contact_check'] = diagnostic
                    turn=diagnostic['observation']['turn']
                    evaluation['evidence_audit']['contact']={'applicability':'applicable',
                        'applicability_reason':'The first operator reply is present and can be checked against the contact rule.',
                        'quote_turn':turn,'evidence_quote':conversation.transcript[turn-1].text[:250]}
                evaluation['tone_observations'] = tone_observations(conversation)
                evaluation['source_checks']=apply_source_checks(conversation,criteria,output.criteria,evaluation['evidence_audit'])
                score, contributions = calculate_score(criteria,output.criteria)
                evaluation.update(status='ok',criteria=[j.model_dump() for j in output.criteria],score=score,
                    contributions=contributions,needs_review=output.needs_review or s.require_review,
                    review_reason=('Uncalibrated prototype output: human review required. '+output.review_reason).strip() if s.require_review else output.review_reason)
                evaluation.pop('validation_errors',None)
                evaluation.pop('error',None)
                break
            except (ValidationError,ValueError) as exc:
                evaluation['error'] = 'Model judgment failed criterion/evidence validation.'
                evaluation['validation_errors'] = [{'field':'.'.join(str(p) for p in e['loc']),'message':e['msg']} for e in exc.errors(include_input=False)] if isinstance(exc,ValidationError) else [{'message':str(exc)}]
                self.store.put('evaluation',evaluation['id'],evaluation)
                if repair_used or attempt+1 >= s.max_attempts:
                    break
                # Field names/range rules only; never include raw model text in logs/errors.
                repair = ('Return the selected IDs exactly once, exact allowed primitive values, and unique evidence indices from 1 to '+str(len(conversation.transcript))+'. '
                    'Set applicability separately from performance. Cite actual original turns, strongest support first. Positive operator actions require an operator turn. Do not generate quotation fields: the application retrieves original source text. Keep rationale concise and use the original response schema.')
                repair_used = True
            except ProviderError as exc:
                evaluation['error'] = str(exc)
                if not exc.retryable or attempt+1 >= s.max_attempts:
                    break
                time.sleep(max(exc.retry_after,min(2**attempt,8)))
        evaluation['elapsed_seconds'] = round(time.monotonic()-started,3)
        self.store.put('evaluation',evaluation['id'],evaluation)
        return {**self.get_evaluation(evaluation['id']),'cached':False}

    def recheck_contact(self,id):
        """Create a new automatic revision, never overwrite an AI run or appeal."""
        with self.evaluation_lock:
            original = self.store.get('evaluation',id)
            if original['status']!='ok':
                raise ValueError('A successful evaluation is required')
            if original.get('contact_check',{}).get('check_version')==CONTACT_CHECK_VERSION:
                return self.get_evaluation(id)
            existing = [e for e in self.store.all('evaluation') if e.get('derived_from')==id and e.get('contact_check',{}).get('check_version')==CONTACT_CHECK_VERSION]
            if existing:
                return self.get_evaluation(existing[-1]['id'])
            conversation = self.conversation(original['conversation_id'])
            criteria = [Criterion.model_validate(c) for c in self.checklist(original['checklist_version_id'])['criteria']]
            judgments = [Judgment.model_validate(j) for j in original['criteria']]
            diagnostic = apply_contact_check(conversation,criteria,judgments)
            if diagnostic is None:
                return self.get_evaluation(id)
            revision = copy.deepcopy(original)
            revision.update(id=uid('evaluation'),created_at=now(),derived_from=id,contact_check=diagnostic,
                tone_observations=tone_observations(conversation),
                criteria=[j.model_dump() for j in judgments],usage={'input_tokens':0,'output_tokens':0},
                attempts=0,elapsed_seconds=0,needs_review=True,
                review_reason='Source-backed contact recheck only; politeness/empathy and other criteria retain their original judgments and need fresh evaluation for the new tone policy. Prior runs and appeal decisions are preserved separately.')
            revision['model_metadata']['contact_check_version']=CONTACT_CHECK_VERSION
            revision['model_metadata']['tone_policy_version']=TONE_POLICY_VERSION
            revision['model_metadata']['tone_policy_scope']='contact_only_recheck'
            revision['cache_key']=fingerprint({'derived_from':id,'contact_check_version':CONTACT_CHECK_VERSION})
            revision['score'],revision['contributions']=calculate_score(criteria,judgments)
            self.store.put('evaluation',revision['id'],revision)
            return self.get_evaluation(revision['id'])

    def recheck_sources(self,id):
        with self.evaluation_lock:
            original=self.store.get('evaluation',id)
            if original['status']!='ok':raise ValueError('A successful evaluation is required')
            conversation=self.conversation(original['conversation_id'])
            criteria=[Criterion.model_validate(c) for c in self.checklist(original['checklist_version_id'])['criteria']]
            judgments=[Judgment.model_validate(j) for j in original['criteria']]
            audit=copy.deepcopy(original.get('evidence_audit',{}))
            changes=apply_source_checks(conversation,criteria,judgments,audit)
            if not changes:return self.get_evaluation(id)
            revision=copy.deepcopy(original)
            revision.update(id=uid('evaluation'),created_at=now(),derived_from=id,source_checks=changes,
                evidence_audit=audit,criteria=[j.model_dump() for j in judgments],usage={'input_tokens':0,'output_tokens':0},
                attempts=0,elapsed_seconds=0,needs_review=True,
                review_reason='Narrow source checks applied; remaining semantic judgments require review. Prior model run and appeal history are preserved separately.')
            revision['model_metadata']['source_check_version']=SOURCE_CHECK_VERSION
            revision['cache_key']=fingerprint({'derived_from':id,'source_check_version':SOURCE_CHECK_VERSION})
            revision['score'],revision['contributions']=calculate_score(criteria,judgments)
            self.store.put('evaluation',revision['id'],revision)
            return self.get_evaluation(revision['id'])

    def get_evaluation(self,id):
        original = self.store.get('evaluation',id)
        result = copy.deepcopy(original)
        decisions = [d for d in self.store.all('decision') if d['evaluation_id']==id]
        for decision in decisions:
            for judgment in result['criteria']:
                if judgment['criterion_id']==decision['criterion_id']:
                    judgment['value'] = decision['new_value']
                    judgment['rationale'] = decision['reason']
                    judgment['evidence_turns'] = decision['evidence_turns']
        if original['status']=='ok':
            criteria = [Criterion.model_validate(c) for c in self.checklist(original['checklist_version_id'])['criteria']]
            result['score'],result['contributions'] = calculate_score(criteria,[Judgment.model_validate(j) for j in result['criteria']])
        return {'original':original,'final':result,'decisions':decisions,'revision':len(decisions)}

    def appeal(self,evaluation_id,criterion_id,comment):
        view = self.get_evaluation(evaluation_id)
        if view['original']['status']!='ok':
            raise ValueError('Cannot appeal a failed evaluation')
        if criterion_id not in {j['criterion_id'] for j in view['final']['criteria']}:
            raise ValueError('Criterion not found in evaluation')
        if not comment.strip():
            raise ValueError('An appeal comment is required')
        item = {'id':uid('appeal'),'evaluation_id':evaluation_id,'criterion_id':criterion_id,
            'comment':comment,'status':'open','created_at':now(),'evaluation_revision':view['revision']}
        self.store.put('appeal',item['id'],item)
        return item

    def decide(self,appeal_id,action,value,reason,evidence_turns,expected_revision):
        if not reason.strip():
            raise ValueError('A reviewer reason is required')
        if action not in ('confirm','override'):
            raise ValueError('Decision must be confirm or override')
        with self.evaluation_lock:
            appeal = self.store.get('appeal',appeal_id)
            view = self.get_evaluation(appeal['evaluation_id'])
            if appeal['status']!='open' or view['revision']!=expected_revision:
                raise Conflict('Decision is stale or appeal is already closed. Reload the evaluation.')
            judgments = [Judgment.model_validate(j) for j in view['final']['criteria']]
            judgment = next(j for j in judgments if j.criterion_id==appeal['criterion_id'])
            old_value = judgment.value
            if action=='override':
                judgment.value = value
            judgment.rationale = reason
            judgment.evidence_turns = evidence_turns if evidence_turns is not None else judgment.evidence_turns
            # Assignment does not validate Pydantic fields: reparse before semantic checks.
            judgments = [Judgment.model_validate(j.model_dump()) for j in judgments]
            criteria = [Criterion.model_validate(c) for c in self.checklist(view['original']['checklist_version_id'])['criteria']]
            validate_judgments(criteria,judgments,len(self.conversation(view['original']['conversation_id']).transcript))
            decision = {'id':uid('decision'),'appeal_id':appeal_id,'evaluation_id':appeal['evaluation_id'],
                'criterion_id':appeal['criterion_id'],'old_value':old_value,'new_value':judgment.value,
                'reason':reason,'evidence_turns':judgment.evidence_turns,'created_at':now(),'revision':expected_revision+1}
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current = self.store.get('appeal',appeal_id,db)
                rows = db.execute("SELECT payload FROM entities WHERE kind='decision'").fetchall()
                revision = sum(json.loads(row['payload'])['evaluation_id']==appeal['evaluation_id'] for row in rows)
                if current['status']!='open' or revision!=expected_revision:
                    raise Conflict('Concurrent review changed this evaluation. Reload it.')
                current['status'] = 'confirmed' if action=='confirm' else 'overridden'
                self.store.put('appeal',appeal_id,current,db)
                self.store.put('decision',decision['id'],decision,db)
            return self.get_evaluation(appeal['evaluation_id'])

    def evaluation_statuses(self,checklist_id='official-v1'):
        self.checklist(checklist_id)
        statuses={}
        for row in self.store.all('evaluation'):
            if row['checklist_version_id']!=checklist_id:continue
            id=row['conversation_id']
            previous=statuses.get(id,{})
            if row['status']=='ok' or previous.get('status')!='evaluated':
                statuses[id]={'status':'evaluated' if row['status']=='ok' else 'error','evaluation_id':row['id']}
        for job in self.store.all('job'):
            if job['status'] not in ('queued','running') or job['checklist_id']!=checklist_id:continue
            finished={item['conversation_id'] for item in job['items']}
            for id in job['conversation_ids']:
                if id not in finished and statuses.get(id,{}).get('status')!='evaluated':
                    statuses[id]={'status':'queued','job_id':job['id']}
        return statuses

    def create_job(self,dataset,checklist_id='official-v1',force=False,only_unevaluated=False):
        source = self.store.get('dataset',dataset)
        self.checklist(checklist_id)
        if only_unevaluated and force:
            raise ValueError('Pending-only batches cannot force reevaluation')
        with self.import_lock:
            if any(j['status'] in ('queued','running') and j['dataset']==dataset and j['checklist_id']==checklist_id for j in self.store.all('job')):
                raise Conflict('A batch for this dataset and checklist is already running')
            statuses=self.evaluation_statuses(checklist_id)
            ids=[id for id in source['conversation_ids'] if not only_unevaluated or statuses.get(id,{}).get('status')!='evaluated']
            job = {'id':uid('job'),'dataset':dataset,'checklist_id':checklist_id,'force':force,'only_unevaluated':only_unevaluated,
                'status':'queued','created_at':now(),'conversation_ids':ids,'items':[]}
            self.store.put('job',job['id'],job)
        return job

    def run_job(self,id):
        job = self.store.get('job',id)
        job['status']='running'
        self.store.put('job',id,job)
        try:
            for conversation_id in job['conversation_ids']:
                if job.get('only_unevaluated') and self.evaluation_statuses(job['checklist_id']).get(conversation_id,{}).get('status')=='evaluated':
                    result=self.store.get('evaluation',self.evaluation_statuses(job['checklist_id'])[conversation_id]['evaluation_id'])
                    job['items'].append({'conversation_id':conversation_id,'evaluation_id':result['id'],'status':'ok','cached':True})
                    self.store.put('job',id,job)
                    continue
                view = self.evaluate(conversation_id,job['checklist_id'],job['force'])
                result = view['original']
                job['items'].append({'conversation_id':conversation_id,'evaluation_id':result['id'],'status':result['status'],'cached':view['cached']})
                self.store.put('job',id,job)
            job['status'] = 'complete' if all(i['status']=='ok' for i in job['items']) else 'complete_with_errors'
        except Exception:
            job['status']='interrupted'
            job['error']='Job interrupted. Completed evaluations are saved; submit another batch to resume.'
        self.store.put('job',id,job)
        return job

    def export(self,dataset,expected=None,reviewed=False):
        source = self.store.get('dataset',dataset)
        expected = expected if expected is not None else (65 if dataset=='dev' else 10)
        if len(source['conversation_ids'])!=expected:
            raise ValueError(f'Export expects {expected} source records')
        evaluations = [e for e in self.store.all('evaluation') if e['checklist_version_id']=='official-v1']
        selected = {e['conversation_id']:e for e in evaluations}
        results,models,providers = [],set(),set()
        for id in source['conversation_ids']:
            if id not in selected:
                raise ValueError('Some source conversations have not been evaluated. Run a batch before exporting.')
            row = selected[id]
            if reviewed:
                row = self.get_evaluation(row['id'])['final']
            models.add(row['model_metadata']['name'])
            providers.add(row['model_metadata']['provider'])
            if row['status']=='error':
                results.append({'conversation_id':id,'status':'error','criteria':[],'score':None,'error':row['error']})
                continue
            judgments = [Judgment.model_validate(j) for j in row['criteria']]
            criteria = official_checklist().criteria
            validate_judgments(criteria,judgments,len(self.conversation(id).transcript))
            score,_ = calculate_score(criteria,judgments)
            if score['final_score'] is None:
                raise ValueError('Official export requires a calculated score')
            results.append({'conversation_id':id,'status':'ok','criteria':[j.model_dump() for j in judgments],'score':score})
        mode = 'hybrid' if len(providers)>1 else 'local' if providers=={'ollama'} else 'external_api'
        payload = {'schema_version':'1.0','team_name':self.settings.team_name,'model':{'mode':mode,'name':', '.join(sorted(models))},'results':results}
        validate_submission(payload,{id: self.conversation(id) for id in source['conversation_ids']},expected)
        return payload


def validate_submission(payload,conversations,expected):
    if set(payload)!={'schema_version','team_name','model','results'} or payload['schema_version']!='1.0':
        raise ValueError('Invalid submission envelope')
    if not isinstance(payload['team_name'],str) or not payload['team_name'].strip():
        raise ValueError('Team name is required')
    if set(payload['model'])!={'mode','name'} or payload['model']['mode'] not in ('local','external_api','hybrid') or not payload['model']['name']:
        raise ValueError('Invalid model metadata')
    results = payload['results']
    ids = [r['conversation_id'] for r in results]
    if len(ids)!=expected or len(set(ids))!=len(ids) or set(ids)!=set(conversations):
        raise ValueError('Submission IDs do not match the source dataset exactly')
    criteria = official_checklist().criteria
    for row in results:
        if row['status']=='error':
            if set(row)!={'conversation_id','status','criteria','score','error'} or row['criteria']!=[] or row['score'] is not None or not isinstance(row['error'],str) or not row['error']:
                raise ValueError('Malformed error record')
        elif row['status']=='ok':
            if set(row)!={'conversation_id','status','criteria','score'}:
                raise ValueError('Unofficial result fields detected')
            judgments = [Judgment.model_validate(j) for j in row['criteria']]
            validate_judgments(criteria,judgments,len(conversations[row['conversation_id']].transcript))
            score,_ = calculate_score(criteria,judgments)
            if set(row['score'])!={'final_score','critical_flag'} or type(row['score']['final_score']) not in (int,float) or type(row['score']['critical_flag']) is not bool or score!=row['score']:
                raise ValueError('Score does not match criterion values')
        else:
            raise ValueError('Unknown status')
    return {'valid':True,'total':len(ids),'ok':sum(r['status']=='ok' for r in results),'errors':sum(r['status']=='error' for r in results)}


def write_json(path,payload):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temporary.replace(path)
