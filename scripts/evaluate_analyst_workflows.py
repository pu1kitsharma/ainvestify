"""Run complete preparation workflows in an isolated store; never alter live leads."""
import argparse,hashlib,json,sys,tempfile,time,signal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.analyst_pack import prepare_analyst_pack,export_pack,SECTIONS,VERSION,IMPLEMENTATION_HASH,collect_preparation_evidence
from agents.local_models import AnalystModel,PreparationModel,LocalModel,generate_task
from schemas import CompanyEvidence,CompanyProfile,SourcedLead
from store import Store


class EvaluationBudget:
    """Evaluation-only caps; never changes production prompts or model answers."""
    def __init__(self, model, max_corrections=None, max_calls=None):
        self.model=model;self.max_corrections=max_corrections;self.max_calls=max_calls
        self.calls=0;self.corrections={};self.denials=[]
        self.last_route={};self.last_response_text=''

    def __getattr__(self, key):
        return getattr(self.model,key)

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        payload=json.loads(evidence)
        key=next((d+'.'+k for d,k,_,text in SECTIONS if instruction.endswith(text)),task)
        if task=='record_extract':key+=':'+','.join(p['passage_id'] for p in payload['passages'])
        self.last_route={'budget_denied':True};self.last_response_text=''
        if self.max_calls is not None and self.calls>=self.max_calls:
            raise RuntimeError('Frozen evaluation inference-call budget exhausted.')
        if attempt>0:
            if self.max_corrections is not None and self.corrections.get(key,0)>=self.max_corrections:
                self.denials.append({'task':key,'attempt':attempt})
                raise ValueError('Frozen evaluation allows no further corrections for this section.')
            self.corrections[key]=self.corrections.get(key,0)+1
        self.calls+=1
        try:
            return self.model.generate_for_task(task,instruction,evidence,schema,attempt=attempt)
        finally:
            self.last_route=dict(getattr(self.model,'last_route',{}))
            self.last_response_text=getattr(self.model,'last_response_text','')


def workflow_metrics(pack):
    sections=pack.get('sections',{})
    return {'completed_sections':sum(s['status']=='complete' for s in sections.values()),
            'expected_sections':len(SECTIONS),
            'completion_rate':sum(s['status']=='complete' for s in sections.values())/len(SECTIONS),
            'completed_documents':[k for k,v in pack.get('documents',{}).items() if v['status']=='complete'],
            'model_calls':sum(r.get('invoked',True) for r in pack.get('attempts',[])),
            'correction_attempts':sum(r.get('invoked',True) and r.get('attempt',0)>0 for r in pack.get('attempts',[])),
            'inference_seconds':round(sum(r['elapsed_seconds'] for r in pack.get('attempts',[])),2),
            'independently_audited_factual_errors':None,'actionable_sections':None}


def select_completed_profile(reports,case_ids):
    """No automatic promotion from schema or self-review scores alone."""
    eligible=[]
    groups={}
    for report in reports:
        pack=report.get('pack',{})
        if pack.get('version')!=VERSION or pack.get('implementation_hash')!=IMPLEMENTATION_HASH:continue
        key=(report['model'],json.dumps(report.get('settings',{}),sort_keys=True))
        groups.setdefault(key,[]).append(report)
    for (model,settings),rows in groups.items():
        if len(rows)!=len(case_ids) or {r['case_id'] for r in rows}!=set(case_ids):continue
        if all(r.get('metrics',{}).get('completion_rate')==1 and r.get('audit',{}).get('reviewed') is True
               and r['audit'].get('factual_errors')==0 and r['audit'].get('actionable_sections')==len(SECTIONS) for r in rows):
            eligible.append((sum(r['elapsed_seconds'] for r in rows),model,settings))
    if not eligible:return None
    seconds,model,settings=min(eligible)
    return {'model':model,'settings':json.loads(settings),'aggregate_seconds':seconds}


def select_completed_model(reports,case_ids):
    selected=select_completed_profile(reports,case_ids)
    return selected['model'] if selected else None


def evaluate_compact_diligence(case, model, *, max_seconds=60):
    """One isolated capability call; never select a profile or publish a pack."""
    from agents.analyst_pack import (CompactDiligencePair, COMPACT_DILIGENCE_METHOD,
                                    expand_compact_requests, Action)
    from agents.preparation_budget import PreparationBudget, preparation_budget
    facts=[{'id':e['id'],'quote':e.get('quote') or e['value'],
            'category':e['field'],'source_url':e['source_url'],
            'origin':e.get('origin'),'status':'source_reported'} for e in case['evidence']]
    payload={'company':case['company'],'website':case['website'],
             'input_scope':case.get('input_scope'),'facts':facts}
    evidence=json.dumps(payload,separators=(',',':'))
    schema=CompactDiligencePair.model_json_schema()
    budget=PreparationBudget(max_seconds=min(max_seconds,60),max_calls=1,max_requests=1)
    report={'case_id':case['id'],'evaluation':'compact_diligence_capability',
            'implementation_hash':IMPLEMENTATION_HASH,'model':model.name,
            'input_kind':case.get('kind'),'input':payload,'instruction':COMPACT_DILIGENCE_METHOD,
            'schema':schema,'input_sha256':hashlib.sha256(evidence.encode()).hexdigest(),
            'schema_sha256':hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),
            'status':'failed','live_data_updated':False,'selected_model':None,
            'acceptance':{'two_distinct_useful_plans':None,'financial_meaning':None,
                          'records_answer_questions':None,'scope_and_source_qualifications':None,
                          'unsupported_business_assertions':None,'independent_audit_required':True}}
    try:
        with preparation_budget(budget):
            pair=generate_task(model,'compact_diligence',COMPACT_DILIGENCE_METHOD,evidence,CompactDiligencePair)
            report['compact_output']=pair.model_dump()
            if pair.questions[0].dimension!='unit_economics':
                raise ValueError('The capability gate requires a first unit-economics plan.')
            requests=expand_compact_requests(pair,facts)
            report['requests']=[r.model_dump() for r in requests]
            report['actions']=[Action(analysis_plan=r.analysis_plan,fact_ids=r.fact_ids).model_dump() for r in requests]
            budget.remaining()
            report['status']='validated_awaiting_independent_audit'
    except Exception as exc:
        report['error']=str(exc)
    finally:
        report['raw_response']=getattr(model,'last_response_text','')
        report['route']=dict(getattr(model,'last_call',None) or getattr(model,'last_route',{}))
        report['budget']=budget.snapshot()
        report['elapsed_seconds']=report['budget']['elapsed_seconds']
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cases',required=True);p.add_argument('--output',required=True);p.add_argument('--model');p.add_argument('--review-model');p.add_argument('--no-review-thinking',action='store_true');p.add_argument('--collect-public',action='store_true');p.add_argument('--thinking',action='store_true');p.add_argument('--context',type=int);p.add_argument('--tokens',type=int,default=2200)
    p.add_argument('--max-corrections',type=int);p.add_argument('--max-calls',type=int);p.add_argument('--max-seconds',type=int);p.add_argument('--reference',help='Hash a reference artifact for the audit; never pass it to inference.')
    p.add_argument('--compact-diligence-only',action='store_true',help='One fast local call for two typed plans; no workflow, collection, retries or promotion.')
    a=p.parse_args()
    for key in ('max_calls','max_seconds','tokens','context'):
        if getattr(a,key) is not None and getattr(a,key)<=0:p.error(key+' must be positive')
    if a.max_corrections is not None and a.max_corrections<0:p.error('max_corrections must not be negative')
    cases=json.loads(Path(a.cases).read_text());out=Path(a.output)
    if a.compact_diligence_only:
        if not a.model or len(cases)!=1 or a.collect_public or a.thinking or a.review_model:
            p.error('The compact gate requires one frozen case, an explicit local model and no collection/thinking/reviewer.')
        # Exclusive directory creation protects every original observation.
        reference_hash=hashlib.sha256(Path(a.reference).read_bytes()).hexdigest() if a.reference else None
        out.mkdir(parents=True,exist_ok=False)
        model=LocalModel(a.model,thinking=False,max_tokens=min(a.tokens,2000),context_tokens=a.context or 8192)
        report=evaluate_compact_diligence(cases[0],model,max_seconds=a.max_seconds or 60)
        if reference_hash:report['reference_sha256']=reference_hash
        (out/(cases[0]['id']+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ('status','elapsed_seconds','budget')}),flush=True)
        return 0 if report['status']=='validated_awaiting_independent_audit' else 1
    out.mkdir(parents=True,exist_ok=True)
    if any((out/(case['id']+'.json')).exists() for case in cases):
        p.error('Use a fresh output directory; original evaluation reports must not be overwritten.')
    model=AnalystModel(a.model,review_model=a.review_model,review_thinking=False if a.no_review_thinking else None,thinking=a.thinking,max_tokens=a.tokens,context_tokens=a.context or (12288 if a.thinking else 8192)) if a.model else PreparationModel()
    reports=[]
    for case in cases:
        bounded=EvaluationBudget(model,a.max_corrections,a.max_calls)
        start=time.monotonic();report={'case_id':case['id'],'input_hash':hashlib.sha256(json.dumps(case,sort_keys=True).encode()).hexdigest(),'model':a.model or 'production_router','settings':{'profile':'section_router' if a.model else 'production_router','review_model':getattr(model,'review_model',None),'review_thinking':getattr(model,'review_thinking',True),'reasoning_budget':getattr(model,'reasoning_budget',None),'thinking':a.thinking,'tokens':a.tokens,'context':a.context or (12288 if a.thinking else 8192)},'input_kind':case.get('kind','public_source_excerpt'),'region':case['region'],'sector':case['sector'],'live_data_updated':False}
        report['limits']={'max_corrections_per_stage':a.max_corrections,'max_calls':a.max_calls,'max_seconds':a.max_seconds}
        if a.reference:report['reference_sha256']=hashlib.sha256(Path(a.reference).read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory,Store(Path(directory)/'evaluation.db') as s:
            profile=CompanyProfile(tenant_id='evaluation',name=case['company'],website=case['website'],evidence=[CompanyEvidence(**e) for e in case['evidence']])
            lead=SourcedLead(tenant_id='evaluation',company_id=profile.id,company_name=profile.name,company_profile=profile);s.save_company(profile);s.save_lead(lead)
            path=out/(case['id']+'.json')
            def progress(pack):
                report.update(pack=pack,metrics=workflow_metrics(pack),elapsed_seconds=round(time.monotonic()-start,2))
                report['actual_inference_calls']=bounded.calls;report['denied_corrections']=bounded.denials
                path.write_text(json.dumps(report,indent=2)+'\n')
            def deadline(signum,frame):
                raise TimeoutError('Frozen evaluation wall-clock budget exhausted.')
            previous_handler=None
            budget=None
            try:
                limit=min(a.max_seconds or 120,120)
                previous_handler=signal.signal(signal.SIGALRM,deadline)
                signal.setitimer(signal.ITIMER_REAL,max(.001,limit-(time.monotonic()-start)))
                from agents.preparation_budget import PreparationBudget,preparation_budget
                # Leave a small margin for saving the partial pack before the
                # outer process cap; exercise production cancellation itself.
                budget=PreparationBudget(max_seconds=max(.01,min(a.max_seconds or 120,120)-(time.monotonic()-start)-.25),max_calls=min(a.max_calls or 24,100))
                with preparation_budget(budget):
                    if a.collect_public:
                        lead=collect_preparation_evidence(s,lead)
                        report['input_kind']='observed_website_and_commercial_pages'
                        report['source_collection']=s.get_workspace('evaluation',lead_id=lead.id).research.get('preparation_sources',{})
                    report['input_evidence']=[e.model_dump(mode='json') for e in lead.company_profile.evidence]
                    w=prepare_analyst_pack(s,lead,bounded,progress,budget=budget);progress(w.analyst_pack)
                (out/(case['id']+'.md')).write_text(export_pack(w.analyst_pack))
            except (Exception,KeyboardInterrupt) as exc:
                report['error']=str(exc) or 'Interrupted';path.write_text(json.dumps(report,indent=2)+'\n')
                if isinstance(exc,KeyboardInterrupt):return 1
            finally:
                if previous_handler is not None:
                    signal.setitimer(signal.ITIMER_REAL,0)
                    signal.signal(signal.SIGALRM,previous_handler)
                report['elapsed_seconds']=round(time.monotonic()-start,2)
                if budget:report['budget']=budget.snapshot()
                path.write_text(json.dumps(report,indent=2)+'\n')
        reports.append(report);print(case['id'],report.get('metrics'),flush=True)
    selected=select_completed_profile(reports,[c['id'] for c in cases])
    (out/'selection.json').write_text(json.dumps({'selected_model':selected['model'] if selected else None,'selected_profile':selected,'reason':'Requires complete workflows and independent factual/actionability audits across every case; never promotes from self-review alone.'},indent=2)+'\n')
    return 0 if all(r.get('metrics',{}).get('completion_rate')==1 for r in reports) else 1

if __name__=='__main__':sys.exit(main())
