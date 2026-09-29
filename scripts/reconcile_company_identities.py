"""Resolve ambiguous same-name public company records without deleting history.

Default is a read-only candidate listing. --apply makes bounded public-evidence
model calls and stores their exact identity decisions as reversible metadata.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.discovery.company_identity import name_key,same_company,resolve_profile_identity,unique_leads
from agents.research.public_research import PublicResearchModel
from agents.preparation.preparation_budget import PreparationBudget,preparation_budget
from store import Store


def reconcile(store,tenant,*,apply=False,model=None):
    leads=store.list_leads(tenant);seen=[];result=[]
    for lead in leads:
        p=lead.company_profile
        if not p:continue
        matches=[other for other in seen if name_key(other.name)==name_key(p.name)]
        if matches and not any(same_company(p,other) for other in matches):
            row={'lead_id':lead.id,'company':p.name,'possible_matches':[o.id for o in matches]}
            if apply:
                found,proof=resolve_profile_identity(p,matches,model or PublicResearchModel(),[],lambda:None)
                row['proof']=proof
                if found:
                    p.provenance['identity_resolution']=proof
                    store.save_company(p);store.save_lead(lead)
                    row['matched_company_id']=found.id
            result.append(row)
        seen.append(p)
    return {'comparisons':result,'stored_leads':len(leads),'distinct_companies':len(unique_leads(store.list_leads(tenant)))}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--tenant',default='default_tenant')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    with Store() as store:
        active=[w.automation.id for w in store.list_workspaces(args.tenant) if w.automation and w.automation.status in {'queued','running'}]+[r.id for r in store.list_web_runs(args.tenant) if r.status in {'queued','running'}]
        if active:raise SystemExit('Wait for active jobs before identity reconciliation.')
        with preparation_budget(PreparationBudget(max_seconds=30,max_calls=3,max_requests=3)) as budget:
            result=reconcile(store,args.tenant,apply=args.apply)
            result['budget']=budget.snapshot()
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='comparisons'},indent=2))
    print('Comparisons:',len(result['comparisons']))
