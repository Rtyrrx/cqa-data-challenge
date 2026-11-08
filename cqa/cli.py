import argparse
import json
import sys
from pathlib import Path

import httpx

from .config import ROOT, Settings
from .domain import Conversation
from .service import Service, validate_submission, write_json


def print_json(payload):
    print(json.dumps(payload,ensure_ascii=False,indent=2))


def main():
    parser = argparse.ArgumentParser(description='CQA: import, evaluate, review, export. No interface required.')
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor',help='Check configuration and model availability without generating tokens')
    command = sub.add_parser('recheck-contact',help='Create a source-backed contact correction; preserve original run')
    command.add_argument('evaluation_id')
    command = sub.add_parser('import',help='Import organizer JSON or fetch from configured URL')
    command.add_argument('--dataset',choices=['dev','prod'],required=True)
    command.add_argument('--file',type=Path)
    command.add_argument('--group-id')
    command.add_argument('--expected',type=int)
    command = sub.add_parser('evaluate')
    command.add_argument('conversation_id')
    command.add_argument('--checklist',default='official-v1')
    command.add_argument('--force',action='store_true')
    command = sub.add_parser('batch')
    command.add_argument('--dataset',choices=['dev','prod'],required=True)
    command.add_argument('--checklist',default='official-v1')
    command.add_argument('--force',action='store_true')
    command = sub.add_parser('export')
    command.add_argument('--dataset',choices=['dev','prod'],required=True)
    command.add_argument('--output',type=Path)
    command.add_argument('--expected',type=int)
    command.add_argument('--reviewed',action='store_true')
    command = sub.add_parser('validate')
    command.add_argument('file',type=Path)
    command.add_argument('--dataset',choices=['dev','prod'],required=True)
    command.add_argument('--expected',type=int)
    command = sub.add_parser('serve')
    command.add_argument('--port',type=int,default=8000)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command=='serve':
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings),host='127.0.0.1',port=args.port)
        return
    service = Service(settings)
    try:
        if args.command=='doctor':
            details = {'provider':settings.provider,'model':settings.model,'db_ready':True,'model_available':False,'usage_last_24h':service.store.usage()}
            try:
                if settings.provider=='groq':
                    if not settings.api_key:
                        details['action']='Set GROQ_API_KEY in .env, or select Ollama.'
                    else:
                        response = httpx.get('https://api.groq.com/openai/v1/models',headers={'Authorization':'Bearer '+settings.api_key},timeout=10)
                        details['model_available']=response.status_code==200 and any(m['id']==settings.model for m in response.json().get('data',[]))
                else:
                    response = httpx.get(settings.ollama_url+'/api/tags',timeout=5)
                    details['model_available']=response.status_code==200 and any(m.get('name')==settings.model for m in response.json().get('models',[]))
                    if not details['model_available']:
                        details['action']='Start Ollama and pull '+settings.model
            except (httpx.HTTPError,ValueError,KeyError):
                details['action']='Model service is unavailable. Start Ollama or check Groq/network configuration.'
            print_json(details)
            if not details['model_available']:
                return 2
        elif args.command=='recheck-contact':
            print_json(service.recheck_contact(args.evaluation_id))
        elif args.command=='import':
            result = service.import_data(json.loads(args.file.read_text(encoding='utf-8-sig')),args.dataset,args.expected) if args.file else service.fetch_dataset(args.dataset,args.group_id,args.expected)
            print_json(result)
        elif args.command=='evaluate':
            result = service.evaluate(args.conversation_id,args.checklist,args.force)
            print_json(result)
            return 0 if result['original']['status']=='ok' else 2
        elif args.command=='batch':
            job = service.create_job(args.dataset,args.checklist,args.force)
            print('Job '+job['id']+' started; each completed evaluation is persisted.',file=sys.stderr,flush=True)
            result = service.run_job(job['id'])
            print_json(result)
            return 0 if result['status']=='complete' else 2
        elif args.command=='export':
            result = service.export(args.dataset,args.expected,args.reviewed)
            path = args.output or ROOT/'results'/args.dataset/'results.json'
            write_json(path,result)
            print_json({'saved':str(path.resolve()),'total':len(result['results']),'errors':sum(r['status']=='error' for r in result['results']),'reviewed':args.reviewed})
        elif args.command=='validate':
            source = service.store.get('dataset',args.dataset)
            conversations = {id:service.conversation(id) for id in source['conversation_ids']}
            print_json(validate_submission(json.loads(args.file.read_text(encoding='utf-8-sig')),conversations,args.expected or (65 if args.dataset=='dev' else 10)))
    except (ValueError,KeyError,OSError):
        # Errors from controlled domain code are safe; OS errors can expose private paths.
        exc = sys.exc_info()[1]
        print_json({'error':str(exc) if isinstance(exc,(ValueError,KeyError)) else 'File operation failed; check the input/output path.'})
        return 2
    finally:
        service.provider.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
