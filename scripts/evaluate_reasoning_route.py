"""Replay the recorded reasoning failure without altering live company records."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pydantic import Field, create_model
from typing import Literal
from agents.claim_grounding import validate_numeric_claims, validate_outcome_claims
from agents.local_models import PreparationModel, generate_task
from agents.investment_case import WorkProduct, WORK, work_instruction, validate_product
from agents.investment_practice import practice_instruction
from agents.preparation_quality import review_preparation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,help='JSON containing company evidence and recorded draft')
    parser.add_argument('--output',required=True)
    parser.add_argument('--fresh',action='store_true',help='Generate from evidence without anchoring on the failed draft; uses current production instructions.')
    args=parser.parse_args()
    case=json.loads(Path(args.input).read_text())
    model=PreparationModel(); started=time.monotonic()
    report={'input_file':args.input,'case':case['company'],'live_data_updated':False,'calls':[]}
    path=Path(args.output)
    def save():path.write_text(json.dumps(report,indent=2)+'\n')
    try:
        review={'issues':[]} if args.fresh else review_preparation(model,'investment_case',case['payload'],case['draft'])
        report['original_review']=review
        if not args.fresh:report['calls'].append(model.last_route)
        save()
        print('Original quantitative verdict:',review.get('checks',{}).get('quantitative_logic',{}).get('verdict','fresh generation'),flush=True)
        ids=[e['id'] for e in case['payload']['sources']]
        schema=create_model('CitedWorkProduct',__base__=WorkProduct,evidence_ids=(list[Literal[tuple(ids)]],Field(min_length=1,max_length=12)))
        instruction=practice_instruction('investment_case',work_instruction('investment_case') + ('\nAddress these review questions where supported by the evidence: '+json.dumps(review['issues']) if review['issues'] else ''))
        for attempt in range(2):
            row={'attempt':attempt}
            report.setdefault('attempts',[]).append(row)
            try:
                result=generate_task(model,'investment_case',instruction,json.dumps(case['payload']),schema,attempt=attempt)
                row['draft']=result.model_dump();report['calls'].append(model.last_route);save()
                validate_product(result)
                validate_numeric_claims(result,case['payload'])
                validate_outcome_claims(result,case['payload'])
                row['review']=review_preparation(model,'investment_case',case['payload'],result)
                report['calls'].append(model.last_route);save()
                if row['review']['issues'] and not attempt:
                    raise ValueError('; '.join(i['correction'] for i in row['review']['issues']))
                report['revised_draft']=result.model_dump()
                report['revised_review']=row['review']
                report['status']='needs_review' if row['review']['issues'] else 'checked_draft'
                break
            except ValueError as exc:
                row['error']=str(exc)
                row['raw_response']=model.last_response_text
                save()
                if attempt:raise
                instruction+=' Correct this problem: '+str(exc)[:500]
                print('Retrying after validation:',str(exc)[:150],flush=True)
        print('Revised draft saved',flush=True)
    except Exception as exc:
        report['error']=str(exc)
        report['calls'].append(model.last_route)
        print('Evaluation error:',str(exc),flush=True)
    report['elapsed_seconds']=round(time.monotonic()-started,2)
    save()
    print('Report saved:',args.output,flush=True)

if __name__=='__main__':main()
