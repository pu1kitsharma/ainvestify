"""Replay the recorded reasoning failure without altering live company records."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.local_models import PreparationModel, generate_task
from agents.investment_case import (VERSION, WORK, work_instruction, work_product_schema,
                                   validate_work_product, revision_context, REVISION_INSTRUCTION,
                                   GENERATION_INSTRUCTION)
from agents.investment_practice import practice_instruction, practice_manifest
from agents.preparation_quality import review_preparation, review_passed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,help='JSON containing company evidence and recorded draft')
    parser.add_argument('--output',required=True)
    parser.add_argument('--fresh',action='store_true',help='Generate from evidence without anchoring on the failed draft; uses current production instructions.')
    parser.add_argument('--stage', choices=list(WORK), default='investment_case')
    args=parser.parse_args()
    case=json.loads(Path(args.input).read_text())
    model=PreparationModel(); started=time.monotonic()
    report={'input_file':args.input,'case':case['company'],'stage':args.stage,
            'input_sha256':hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
            'contract_version':VERSION,'practice':practice_manifest(args.stage),
            'live_data_updated':False,'calls':[], 'status':'running',
            'limitation':'Automated critique is not independent verification of investment quality.'}
    path=Path(args.output)
    def save():path.write_text(json.dumps(report,indent=2)+'\n')
    try:
        review={'issues':[]} if args.fresh else review_preparation(model,args.stage,case['payload'],case['draft'])
        report['original_review']=review
        if not args.fresh:report['calls'].append(model.last_route)
        save()
        print('Original quantitative verdict:',review.get('checks',{}).get('quantitative_logic',{}).get('verdict','fresh generation'),flush=True)
        ids=[e['id'] for e in case['payload']['sources']]
        schema=work_product_schema(args.stage,ids)
        report['schema_sha256']=hashlib.sha256(json.dumps(schema.model_json_schema(),sort_keys=True).encode()).hexdigest()
        instruction=practice_instruction(args.stage,work_instruction(args.stage))
        payload=case['payload']
        if not args.fresh and review['issues']:
            payload=revision_context(payload,'; '.join(i['correction'] for i in review['issues']),raw_response=json.dumps(case['draft']))
            instruction+=REVISION_INSTRUCTION
        for attempt in range(2):
            row={'attempt':attempt}
            report.setdefault('attempts',[]).append(row)
            result=None
            try:
                try:
                    result=generate_task(model,args.stage,instruction+GENERATION_INSTRUCTION,json.dumps(payload),schema,attempt=attempt)
                finally:
                    report['calls'].append(dict(model.last_route))
                row['draft']=result.model_dump();save()
                validate_work_product(result,payload)
                row['review']=review_preparation(model,args.stage,payload,result)
                report['calls'].append(model.last_route);save()
                if row['review']['issues'] and not attempt:
                    raise ValueError('; '.join(i['correction'] for i in row['review']['issues']))
                report['revised_draft']=result.model_dump()
                report['revised_review']=row['review']
                report['status']='checked_draft' if review_passed(row['review']) else 'needs_review'
                break
            except (ValueError,TypeError) as exc:
                row['error']=str(exc)
                row['raw_response']=model.last_response_text
                save()
                if attempt:raise
                payload=revision_context(payload,exc,result,getattr(model,'last_response_text',''))
                instruction+=REVISION_INSTRUCTION
                print('Retrying after validation:',str(exc)[:150],flush=True)
        print('Revised draft saved',flush=True)
    except Exception as exc:
        report['error']=str(exc)
        report['status']='failed'
        print('Evaluation error:',str(exc),flush=True)
    except KeyboardInterrupt:
        report['status']='interrupted'
    report['elapsed_seconds']=round(time.monotonic()-started,2)
    save()
    print('Report saved:',args.output,flush=True)
    return 0 if report['status']=='checked_draft' else 1

if __name__=='__main__':sys.exit(main())
