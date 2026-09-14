"""Probe the automated critic with a clean draft and known material defects."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.local_models import LocalModel
from agents.preparation_quality import review_preparation


def run(output):
    model=LocalModel()
    report=json.loads(Path('evals/investment_preparation/phi4-mini-results.json').read_text())
    cases=json.loads(Path('evals/investment_preparation/cases.json').read_text())
    rows=[]
    for name, should_flag in [('hotel_costs',False),('prerevenue_biotech',True)]:
        case=next(c for c in cases if c['id']==name)
        draft=next(r['output'] for r in report['results'] if r['case']==name and r['mode']=='practice')
        review=review_preparation(model,case['stage'],case['input'],draft)
        rows.append({'case':name,'expected_material_issue':should_flag,'review':review,
                     'expected_behavior':bool(review['issues'])==should_flag})
        Path(output).write_text(json.dumps(rows,indent=2))
        print(name,rows[-1],flush=True)
    draft={'business':'The company has secured investment and grown revenue rapidly.',
           'reason_to_meet':'The funding proves rapid business growth.', 'main_risk':'Delivery costs need checking.',
           'first_question':'Can you share the revenue ledger?','evidence_ids':['C9']}
    case=next(c for c in cases if c['id']=='unverified_growth')
    review=review_preparation(model,'research',case['input'],draft)
    rows.append({'case':'funding_is_not_growth','expected_material_issue':True,'review':review,
                 'expected_behavior':bool(review['issues'])})
    Path(output).write_text(json.dumps(rows,indent=2))
    print(rows[-1],flush=True)


if __name__=='__main__':
    run(sys.argv[1])
