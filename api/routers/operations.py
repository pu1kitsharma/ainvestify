"""Local operating workspaces. No external sending, signing or money movement."""
from typing import Literal, Optional
import uuid
import re
import logging
import traceback
from threading import Lock
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from api.deps import get_store, get_tenant_id, get_reviewer
from agents.datasets import SOURCES
from agents.local_models import MODEL_JOB_SLOT, PreparationModel as LocalModel
from agents.operating_workflow import reconcile_workspace, prepare_operating_drafts, workspace_basis
from schemas import utcnow, new_id
from store import Store
from workflow_schemas import WorkspaceAttestation, AutomationRun

from agents.company_metrics import MonthlyUpdate

router = APIRouter(prefix="/api/operations", tags=["operations"])
_worker_id = uuid.uuid4().hex
_submission_lock = Lock()
_model_activity = {}
logger = logging.getLogger(__name__)


@router.get("/datasets")
def datasets(store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    return {"sources": SOURCES, "snapshots": store.list_dataset_snapshots(tenant_id)}


@router.get("/workspaces")
def workspaces(store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id), summary: bool = False, lead_id: Optional[str] = None):
    # Evaluate reads against current evidence but do not mutate on GET.
    result = [reconcile_workspace(store, lead, persist=False) for w in store.list_workspaces(tenant_id)
              if (not lead_id or w.lead_id==lead_id) and (lead := store.get_lead(tenant_id, w.lead_id)) is not None]
    for workspace in result:
        job = workspace.automation
        if job and job.status in {'queued','running'} and job.id in _model_activity and job.worker_id == _worker_id:
            job.phase = _model_activity[job.id]
        if job and job.status in {"queued", "running"} and job.worker_id != _worker_id:
            job.status = "interrupted"
            job.error = "The local worker restarted. Generate AI work again; saved evidence and drafts are retained."
    if summary:
        return [company_work_view(w) for w in result]
    return result


def company_work_view(workspace):
    """Poll current deliverables without transferring old model traces each time."""
    data=workspace.model_dump(mode='json')
    fields=('id','lead_id','revision','basis_hash','automation','metrics','metric_imports','analyst_pack','analyst_pack_history')
    view={k:data[k] for k in fields}
    from agents.analyst_pack import validate_saved_sections
    pack=validate_saved_sections(view['analyst_pack'])
    pack.pop('attempts',None)
    pack.pop('shared',None)
    pack.pop('authored',None)
    pack.pop('author_candidates',None)
    pack.pop('reuse_sections',None)
    pack.get('record',{}).pop('batches',None)
    pack.get('record',{}).pop('passage_cache',None)
    for section in pack.get('sections',{}).values():
        section.pop('candidate',None);section.pop('review_failure',None)
    # Historical prose remains inspectable; low-level inference attempts do not
    # belong in the polling response or the primary preparation interface.
    view['analyst_pack_history']=[{k:p[k] for k in ('version','basis_hash','company','status','sections') if k in p} for p in view['analyst_pack_history']]
    for old in view['analyst_pack_history']:
        for section in old.get('sections',{}).values():
            section.pop('candidate',None);section.pop('review_failure',None)
    return view


class MetricUpdateRequest(BaseModel):
    expected_revision: int
    update: MonthlyUpdate


@router.post("/workspaces/{workspace_id}/metrics")
def save_metrics(workspace_id: str, body: MetricUpdateRequest, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    saved = store.get_workspace(tenant_id, workspace_id=workspace_id)
    if not saved:
        raise HTTPException(404, "Workspace not found")
    if saved.revision != body.expected_revision:
        raise HTTPException(409, "Company records changed. Reload before saving this update.")
    if saved.automation and saved.automation.status in {'queued','running'} and saved.automation.worker_id == _worker_id:
        raise HTTPException(409, "Wait for company research to finish before changing its financial inputs.")
    record = dict(body.update.model_dump(mode='json'), id=new_id('metrics'), recorded_at=utcnow(), status='company_reported')
    saved.metric_updates.append(record)
    saved.events.append({'at':utcnow(), 'action':'company_metrics_added', 'detail':f"Company-reported figures saved for {record['month']}; previous submissions retained."})
    try:
        store.save_workspace(saved, expected_revision=body.expected_revision)
    except ValueError as exc:
        raise HTTPException(409, "Company records changed. Reload before saving.") from exc
    lead = store.get_lead(tenant_id, saved.lead_id)
    return reconcile_workspace(store, lead)


class MetricImportRequest(BaseModel):
    expected_revision: int
    source_name: str = Field(min_length=12, max_length=300)
    text: str = Field(min_length=30, max_length=18000)


@router.post("/workspaces/{workspace_id}/metric-imports", status_code=202)
def import_metrics(workspace_id: str, body: MetricImportRequest, background: BackgroundTasks,
                   store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    with _submission_lock:
        saved = store.get_workspace(tenant_id, workspace_id=workspace_id)
        if not saved:
            raise HTTPException(404, "Workspace not found")
        if saved.revision != body.expected_revision:
            raise HTTPException(409, "Company records changed. Reload before importing this update.")
        if saved.automation and saved.automation.status in {'queued','running'} and saved.automation.worker_id == _worker_id:
            raise HTTPException(409, "Company work is already running. Your update has not been submitted; wait for it to finish.")
        pending = [w for w in store.list_workspaces(tenant_id) if w.automation and w.automation.worker_id == _worker_id and w.automation.status in {'queued','running'}]
        if len(pending) >= 3:
            raise HTTPException(429, "Three company jobs are already queued. Wait for one to finish.")
        item = {'id':new_id('metric_import'),'source_name':body.source_name,'text':body.text,
                'status':'queued','issues':[],'created_at':utcnow()}
        saved.metric_imports.append(item)
        saved.automation = AutomationRun(model=LocalModel().name, worker_id=_worker_id, phase="Queued: read company update and revise the investment case")
        try:
            store.save_workspace(saved, expected_revision=body.expected_revision)
        except ValueError as exc:
            raise HTTPException(409, "Company records changed. Reload before importing.") from exc
        background.add_task(_prepare_job,store.db_path,tenant_id,saved.lead_id,saved.automation.id,True,metric_import_id=item['id'])
        return saved


def _apply_metric_import(store, workspace, import_id, model):
    from agents.metric_extraction import extract_metric_update
    from agents.company_metrics import KEYS, metrics_report
    item=next(i for i in workspace.metric_imports if i['id']==import_id)
    if item['status'] == 'applied':
        return
    workspace.automation.phase = "Reading dated figures from the company update"
    store.save_workspace(workspace,expected_revision=workspace.revision)
    result=extract_metric_update(item['text'],item['source_name'],workspace.company_name,model)
    current=store.get_workspace(workspace.tenant_id,workspace_id=workspace.id)
    if current.revision != workspace.revision:
        raise ValueError('Company records changed during extraction. Resubmit against the latest records.')
    item.update(status='applied' if result['updates'] else 'needs_input',issues=result['issues'],model=result['model'],attempts=result['attempts'],proposals=result['proposals'],completed_at=utcnow())
    active={r['month']:r for r in metrics_report(workspace.metric_updates)['months']}
    accepted=[]
    for row in result['updates']:
        previous=active.get(row['month'],{})
        if previous and previous['currency'] != row['currency']:
            item['issues'].append(f"{row['month']}: existing figures use {previous['currency']}; no automatic currency conversion or replacement was performed.")
            continue
        # A partial update corrects only fields actually quoted, retaining older
        # observations and their individual source references for this month.
        values={key:row.get(key) if row.get(key) is not None else previous.get(key) for key in KEYS}
        field_sources=dict(previous.get('field_sources',{}))
        for key in KEYS:
            if row.get(key) is not None:
                field_sources[key]={'import_id':import_id,'source_name':item['source_name'],'quote':row['citations'][key]['quote']}
            elif previous.get(key) is not None and key not in field_sources:
                field_sources[key]={'record_id':previous['id'],'source_name':previous['source_note']}
        record={**row,**values,'id':new_id('metrics'),'recorded_at':utcnow(),'status':'company_reported',
                'import_id':import_id,'field_sources':field_sources,
                'citations':{**previous.get('citations',{}),**row['citations']}}
        record['source_note']='; '.join(dict.fromkeys(v['source_name'] for v in field_sources.values()))
        workspace.metric_updates.append(record)
        accepted.append(record['id'])
    item['record_ids']=accepted
    item['status']='applied' if accepted else 'needs_input'
    workspace.events.append({'at':utcnow(),'action':'company_update_extracted',
        'detail':f"AI extracted {len(accepted)} dated monthly records; {len(item['issues'])} exceptions retained."})
    store.save_workspace(workspace,expected_revision=workspace.revision)
    if not accepted:
        raise ValueError('No monthly figures could be accepted. See the company update exceptions under Business performance.')


@router.get("/workspaces/{workspace_id}/metrics")
def download_metrics(workspace_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    saved = store.get_workspace(tenant_id, workspace_id=workspace_id)
    if not saved: raise HTTPException(404, "Workspace not found")
    workspace = reconcile_workspace(store,store.get_lead(tenant_id,saved.lead_id),persist=False)
    return Response(metrics_markdown(workspace),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="company-metrics.md"'})


def metrics_markdown(workspace):
    from agents.company_metrics import KEYS
    lines = [f'## {workspace.company_name}: operating metrics', workspace.metrics['note']]
    for row in workspace.metrics['months']:
        lines += [f"### {row['month']} ({row['currency']})", f"Source: {row['source_note']} · Record: {row['id']}"]
        lines += [f"- {label}: {row[key]}" for key,label in KEYS.items() if row.get(key) is not None]
        lines += [f"Source for {KEYS[key]}: {source['source_name']} — {source.get('quote','Manually supplied figure')}" for key,source in row.get('field_sources',{}).items()]
    for calc in workspace.metrics['calculations']:
        lines += [f"### {calc['name']}: {calc['value']} {calc['unit']}", calc['formula'],calc['explanation'],'Input records: '+', '.join(calc['inputs'])]
    for item in workspace.metrics.get('unresolved_calculations',[]):
        lines += [f"### {item['name']} — unresolved",item['reason'],'Input records: '+', '.join(item['inputs'])]
    if not workspace.metrics['months']: lines.append('No dated company operating figures have been supplied. Public product descriptions are not financial statements.')
    return '\n\n'.join(lines)


@router.get("/workspaces/{workspace_id}/data-request")
def data_request(workspace_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    saved = store.get_workspace(tenant_id, workspace_id=workspace_id)
    if not saved:
        raise HTTPException(404, "Workspace not found")
    lead = store.get_lead(tenant_id, saved.lead_id)
    if not lead:
        raise HTTPException(404, "Company not found")
    workspace = reconcile_workspace(store, lead, persist=False)
    lines = [f'# {workspace.company_name} — transaction data request',
             'Internal preparation checklist. Not sent. Reviewed items reflect recorded reviews, not an audit or legal certification.',
             f'Evidence version: {workspace.basis_hash[:12]}']
    for item in workspace.preparation['requests']:
        lines.extend([f"## {item['deliverable']}", f"Workstream: {item['workstream']} · Owner: {item['owner']} · Status: {item['status']}",
                      item['request'], f"Completion criteria: {item['acceptance']}"])
    for item in workspace.preparation['financials']:
        if item['status'] == 'reviewed':
            lines.append(f"Reviewed input: {item['title']}: {item['value']} {item['unit']} — document {item['document_id']}, page {item['source_page']}, block {item['source_block_id']}")
    for item in workspace.preparation['calculations']:
        lines.extend([f"Calculation: {item['name']}: {item['value']} {item['unit']}", item['formula'], item['limitation']])
    lines.extend(f"Process reference: [{r['title']}]({r['url']})" for r in workspace.preparation['references'])
    return Response('\n\n'.join(lines), media_type='text/markdown',
                    headers={'Content-Disposition': 'attachment; filename="transaction-data-request.md"'})


@router.get("/workspaces/{workspace_id}/internal-brief")
def internal_brief(workspace_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    saved = store.get_workspace(tenant_id, workspace_id=workspace_id)
    if not saved:
        raise HTTPException(404, "Workspace not found")
    lead = store.get_lead(tenant_id, saved.lead_id)
    workspace = reconcile_workspace(store, lead, persist=False)
    if workspace.draft_status != 'draft' or not all(d.sections for d in workspace.drafts):
        raise HTTPException(409, "Complete the current company analysis before exporting the internal brief.")
    facts = {e.id:e for e in lead.company_profile.evidence}
    lines = [f'# {workspace.company_name} — internal company brief',
             'AI analysis and proposed experiments. Public source claims are not audited results. This document is not approved for investor release.',
             f'Evidence version: {workspace.basis_hash[:12]}']
    for draft in workspace.drafts:
        lines.extend([f'## {draft.title}', draft.decision])
        for section in draft.sections:
            lines.extend([f'### {section.heading}', section.content, 'Source basis:'])
            for identifier in section.evidence_ids:
                if identifier in facts:
                    evidence = facts[identifier]
                    lines.extend([f'- [{evidence.field}]({evidence.source_url}) — retrieved {evidence.retrieved_at}', f'  Source passage: {evidence.quote}'])
        lines.append('### Next action')
        for task in draft.tasks:
            lines.extend([task.action, f'Deliverable: {task.deliverable}', f'Proposed success rule: {task.success_measure}', 'Required inputs: '+ '; '.join(task.required_inputs)])
    return Response('\n\n'.join(lines), media_type='text/markdown',
                    headers={'Content-Disposition': 'attachment; filename="internal-company-brief.md"'})


def _prepare_job(db_path, tenant_id, lead_id, job_id, brief=False, refresh=False, metric_import_id=None, readiness=False, analyst=False, analyst_model=None, analyst_thinking=False, analyst_review_model=None, analyst_review_thinking=None):
    from agents.preparation_budget import preparation_budget
    with preparation_budget():
        return _run_prepare_job(db_path, tenant_id, lead_id, job_id, brief, refresh, metric_import_id, readiness, analyst, analyst_model, analyst_thinking, analyst_review_model, analyst_review_thinking)


def _run_prepare_job(db_path, tenant_id, lead_id, job_id, brief=False, refresh=False, metric_import_id=None, readiness=False, analyst=False, analyst_model=None, analyst_thinking=False, analyst_review_model=None, analyst_review_thinking=None):
    # All current company-authoring endpoints share the model-authored writer.
    analyst, brief, readiness = True, False, False
    with Store(db_path) as store:
        workspace = store.get_workspace(tenant_id, lead_id=lead_id)
        if not workspace or not workspace.automation or workspace.automation.id != job_id or workspace.automation.status != 'queued':
            return
        workspace.automation.status = "running"
        workspace.automation.phase = "Assessing engagement suitability" if readiness else "Preparing the company brief" if brief else "Drafting company operating plans"
        store.save_workspace(workspace, expected_revision=workspace.revision)
        diagnostic = {}
        try:
            from agents.operating_research import research_company
            if analyst_model and analyst_model != 'auto':
                from agents.local_models import AnalystModel as DirectModel
                model = DirectModel(analyst_model, review_model=analyst_review_model, review_thinking=analyst_review_thinking, thinking=analyst_thinking, max_tokens=4096 if analyst_thinking else 1800, context_tokens=12288 if analyst_thinking else 8192)
            else:
                model = LocalModel()
            def activity(state, position, task='research'):
                active=store.get_workspace(tenant_id,lead_id=lead_id)
                if not active or not active.automation or active.automation.id!=job_id or active.automation.status=='cancelled':
                    raise ValueError('Preparation stopped. Previously saved sections are retained.')
                label = task.replace('review:', 'Reviewing ').replace('_', ' ')
                if analyst:
                    live=store.get_workspace(tenant_id,lead_id=lead_id)
                    label=live.automation.phase if live and live.automation else 'Preparing company work'
                _model_activity[job_id] = (f'{label.capitalize()} · waiting for an inference turn ({position} ahead including current call)'
                    if state=='waiting' else f'{label.capitalize()} · AI is reading the evidence and writing')
            model.on_activity = activity
            analyst = analyst or bool(metric_import_id and workspace.analyst_pack)
            readiness = readiness or bool(metric_import_id and workspace.investment_case)
            if metric_import_id:
                _apply_metric_import(store, workspace, metric_import_id, model)
                lead = store.get_lead(tenant_id, lead_id)
            elif analyst:
                from agents.analyst_pack import collect_preparation_evidence
                lead = collect_preparation_evidence(store, store.get_lead(tenant_id, lead_id), force=refresh)
            else:
                lead = research_company(store, store.get_lead(tenant_id, lead_id), model, force=refresh)
            if analyst:
                from agents.analyst_pack import prepare_analyst_pack
                prepared = prepare_analyst_pack(store, lead, model)
                if prepared.analyst_pack.get('status') != 'complete':
                    raise ValueError(prepared.analyst_pack.get('stop_reason') or 'Preparation is partial. Completed sections are saved; retry only unfinished sections and reviews.')
            elif readiness:
                from agents.investment_case import prepare_investment_case, preparation_failure_message
                prepared = prepare_investment_case(store,lead,model)
                if prepared.investment_case.get('stage_errors'):
                    raise ValueError(preparation_failure_message(prepared.investment_case))
            elif brief:
                from agents.company_brief import prepare_company_brief
                prepare_company_brief(store, lead, model)
            else:
                prepare_operating_drafts(store, lead, model)
            status, error = "completed", None
        except Exception as exc:
            from agents.preparation_budget import PreparationBudgetExceeded
            status = "failed"
            error = str(exc) if isinstance(exc, (ValueError,PreparationBudgetExceeded)) else f"Local generation failed ({type(exc).__name__}). Saved evidence is retained; retry generation."
            if not isinstance(exc, (ValueError,PreparationBudgetExceeded)):
                # Keep stack locations for diagnosis across API restarts without
                # recording source text, model payloads or exception values.
                stack = '\n'.join(f'{frame.filename}:{frame.lineno} in {frame.name}'
                                  for frame in traceback.extract_tb(exc.__traceback__))
                diagnostic = {'error_type': type(exc).__name__, 'error_traceback': stack}
                logger.error('Preparation job %s failed (%s):\n%s', job_id, type(exc).__name__, stack)
        latest = store.get_workspace(tenant_id, lead_id=lead_id)
        _model_activity.pop(job_id, None)
        if latest.automation and latest.automation.id == job_id and latest.automation.status != 'cancelled':
            if metric_import_id and status == 'failed':
                item=next(i for i in latest.metric_imports if i['id']==metric_import_id)
                if item['status'] == 'queued':
                    item.update(status='failed',issues=[error])
            latest.automation.status = status
            latest.automation.error = error
            latest.automation.phase = ("Suitability decision and supported preparation work saved" if readiness else "Company brief, founder pitch and readiness priorities saved" if brief else "Diligence findings, GTM brief, investor narrative and fundraising assessment saved") if status == "completed" else "Generation needs attention"
            if status == 'completed' and analyst:
                latest.automation.phase = 'Research memo, founder proposal, diligence request and readiness plan saved'
            if status=='completed' and ((readiness and latest.investment_case.get('status')=='needs_review') or (brief and latest.company_brief.get('status')=='needs_review')):
                latest.automation.phase = 'Drafts prepared; automated review questions remain unresolved'
            latest.automation.completed_at = utcnow()
            latest.events.append({"at": utcnow(), "action": f"automation_{status}",
                "detail": f"{latest.automation.model}: {latest.automation.phase}.", **diagnostic})
            store.save_workspace(latest, expected_revision=latest.revision)


@router.post("/leads/{lead_id}/preparation-jobs", status_code=202)
def start_analyst_preparation(lead_id: str, background: BackgroundTasks, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id), refresh: bool = False, model: Optional[str] = None, thinking: bool = False, review_model: Optional[str] = None, review_thinking: Optional[bool] = None):
    if (review_model or review_thinking is not None) and (not model or model=='auto'):
        raise HTTPException(422, 'Specify an installed writing model when overriding the review model.')
    with _submission_lock:
        return company_work_view(_queue_prepare(lead_id, background, store, tenant_id, analyst=True, refresh=refresh, analyst_model=model, analyst_thinking=thinking, analyst_review_model=review_model, analyst_review_thinking=review_thinking))


@router.post('/workspaces/{workspace_id}/preparation-jobs/{job_id}/stop')
def stop_preparation(workspace_id: str, job_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    with _submission_lock:
        workspace=store.get_workspace(tenant_id,workspace_id=workspace_id)
        if not workspace:raise HTTPException(404,'Workspace not found')
        job=workspace.automation
        if not job or job.id!=job_id:raise HTTPException(409,'This preparation job has been replaced. Refresh company work.')
        if job.status in {'queued','running'}:
            job.status='cancelled';job.completed_at=utcnow();job.error=None
            job.phase='Preparation stopped. Saved sections are retained; an in-flight model call may finish before another job starts.'
            workspace.events.append({'at':utcnow(),'action':'automation_cancelled','detail':'Preparation stopped; previously saved work retained.'})
            store.save_workspace(workspace,expected_revision=workspace.revision)
            _model_activity.pop(job_id,None)
        return company_work_view(workspace)


@router.get("/workspaces/{workspace_id}/preparation-pack")
def download_analyst_pack(workspace_id: str, document: Optional[str] = None, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    from agents.analyst_pack import current_pack, export_pack, TITLES
    saved = store.get_workspace(tenant_id, workspace_id=workspace_id)
    if not saved: raise HTTPException(404, 'Workspace not found')
    w = reconcile_workspace(store, store.get_lead(tenant_id, saved.lead_id), persist=False)
    if not current_pack(w): raise HTTPException(409, 'Regenerate preparation using current company inputs.')
    if document and document not in TITLES: raise HTTPException(422, 'Unknown document')
    return Response(export_pack(w.analyst_pack, document), media_type='text/markdown', headers={'Content-Disposition':'attachment; filename="company-preparation.md"'})


@router.post("/leads/{lead_id}/readiness-jobs", status_code=202)
def start_readiness(lead_id: str, background: BackgroundTasks, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id), refresh: bool = False):
    with _submission_lock:
        return _queue_prepare(lead_id,background,store,tenant_id,readiness=True,refresh=refresh)


@router.get("/workspaces/{workspace_id}/investment-case")
def export_investment_case(workspace_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    from agents.investment_case import case_current
    saved=store.get_workspace(tenant_id,workspace_id=workspace_id)
    if not saved:raise HTTPException(404,"Workspace not found")
    lead=store.get_lead(tenant_id,saved.lead_id)
    w=reconcile_workspace(store,lead,persist=False)
    if not case_current(w):raise HTTPException(409,"Prepare the investment case against current company evidence first.")
    case=w.investment_case;fit=case['fit']
    lines=[f'# {w.company_name}: investment preparation','Internal AI draft. Source-reported facts; no outreach, experiment, legal approval or funding is implied.',
        '## Engagement decision',fit['decision'].replace('_',' '),fit.get('maturity','unknown').replace('_',' '),fit['rationale'],'Next action: '+fit['next_action']]
    if case.get('status')=='needs_review':lines.append('Unresolved automated review questions remain. These are working drafts, not verified materials for investors.')
    for product in case.get('products',{}).values():
        lines += ['## '+product['title'],product['purpose'], 'Decision to resolve: '+product['decision_question']]
        for section in product['sections']:lines += ['### '+section['heading'],section['content']]
        lines += ['Next action: '+product['next_action'], 'Complete when: '+product['completion_test']]
        for m, formula in zip(product.get('measurements', []), product.get('measurement_formulas', [])):
            lines += ['Proposed comparison: '+formula, 'Scope: '+m['population_basis'], 'Required records: '+m['left']['record_needed']+'; '+m['right']['record_needed']]
        lines += [f"Required input: {r['record']} — {r['why']}" for r in product['missing_inputs']]
        for claim in product.get('numeric_claims', []):
            lines += ['Source-reported numeric assertion: '+claim['statement'], 'Supporting excerpt: '+claim['quote'], 'Record: '+claim['source_id']]
        for issue in product.get('quality_review',{}).get('issues',[]):
            lines += ['Automated review question (not a confirmed finding): '+issue['correction']]
    lines.append('## Source evidence')
    ids=set(fit['evidence_ids']) | {i for p in case.get('products',{}).values() for i in p['evidence_ids']}
    lines += [f'{e.quote}\nSource: {e.source_url}' for e in lead.company_profile.evidence if e.id in ids]
    lines.append(metrics_markdown(w))
    return Response('\n\n'.join(lines),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="investment-preparation.md"'})


@router.post("/leads/{lead_id}/brief-jobs", status_code=202)
def start_brief(lead_id: str, background: BackgroundTasks, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id), refresh: bool = False):
    with _submission_lock:
        return _queue_prepare(lead_id, background, store, tenant_id, brief=True, refresh=refresh)


@router.get("/workspaces/{workspace_id}/company-brief")
def export_company_brief(workspace_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    from agents.company_brief import brief_current, pitch_text
    saved = store.get_workspace(tenant_id, workspace_id=workspace_id)
    if not saved:
        raise HTTPException(404, "Workspace not found")
    lead = store.get_lead(tenant_id, saved.lead_id)
    if not lead:
        raise HTTPException(404, "Company not found")
    workspace = reconcile_workspace(store, lead, persist=False)
    if workspace.investment_case.get('basis_hash')==workspace.basis_hash and workspace.investment_case.get('fit',{}).get('decision')=='do_not_pursue':
        raise HTTPException(409,'The current engagement decision does not support an incubation pitch. Download the investment-case decision instead.')
    if not brief_current(workspace):
        raise HTTPException(409, "Finish or update the company brief before downloading.")
    pack = workspace.company_brief
    r = pack['research']
    lines = [f'# {lead.company_name} — company brief', 'Internal draft. Company statements are source-reported; proposed work and the founder email have not been executed or sent.',
        '## Research', '### What the company does', r['business'], '### Why meet the founders', r['reason_to_meet'], '### Main risk', r['main_risk'], '### Ask first', r['first_question'],
        '## Founder pitch', pitch_text(lead.company_name, pack['pitch']), '## Investment readiness priorities']
    if pack.get('status')=='needs_review':
        lines.insert(2,'Unresolved automated review questions remain. Do not treat this draft as verified investor material.')
    for i, item in enumerate(pack['readiness']['priorities'], 1):
        lines.extend([f"### {i}. {item['title']}", item['investor_question'], item['why_now'], "Required input: "+item['required_input'], item['action'], f"Deliverable: {item['output']}", f"Complete when: {item['done_when']}"])
    questions=[issue['correction'] for stage in ('research','pitch','readiness') for issue in pack[stage].get('quality_review',{}).get('issues',[])]
    if questions:
        lines += ['## Unresolved automated review questions', 'These questions are AI proposed, not confirmed findings.'] + questions
    lines.append('## Company evidence beyond the product description')
    for title, fields in [('Team and experience', {'team'}), ('Founder requests', {'founder_ask'}), ('Market and alternatives', {'market','competition'})]:
        selected = [e for e in lead.company_profile.evidence if e.field in fields][:2]
        lines.append('### '+title)
        if not selected:
            lines.append('Not established in the collected evidence.')
        for evidence in selected:
            value = evidence.value
            target = re.search(r'(?:intros? to|introductions to)\s+([^.!?\n]+)',value,re.I) if evidence.field == 'founder_ask' else None
            if target:
                value = 'The founders request introductions to '+target.group(1)+'.'
            else:
                value = re.sub(r'^.*?Active Founders\s+','',value)
            if evidence.field == 'team':
                sentences = [s for s in re.split(r'(?<=[.!?])\s+',value.split('The problem')[0]) if re.search(r'[.!?]$',s)]
                value = ' '.join(dict.fromkeys(sentences)) or value
            lines.append(f'{value}\n\nSource: {evidence.source_url}')
    lines.append(metrics_markdown(workspace))
    ids = {i for stage in ('research','pitch','readiness') for i in pack[stage]['evidence_ids']}
    lines.append('## Source passages')
    lines.extend(f'- [{e.field}]({e.source_url}): {e.quote}' for e in lead.company_profile.evidence if e.id in ids)
    return Response('\n\n'.join(lines), media_type='text/markdown', headers={'Content-Disposition':'attachment; filename="company-brief.md"'})


@router.post("/leads/{lead_id}/prepare-jobs", status_code=202)
def start_prepare(lead_id: str, background: BackgroundTasks, store: Store = Depends(get_store),
                  tenant_id: str = Depends(get_tenant_id)):
    with _submission_lock:
        return _queue_prepare(lead_id, background, store, tenant_id)


def _queue_prepare(lead_id, background, store, tenant_id, brief=False, refresh=False, readiness=False, analyst=False, analyst_model=None, analyst_thinking=False, analyst_review_model=None, analyst_review_thinking=None):
    analyst, brief, readiness = True, False, False
    lead = store.get_lead(tenant_id, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not lead.company_profile or not any(e.field in {"offering", "business_model", "traction"} for e in lead.company_profile.evidence):
        raise HTTPException(409, "Establish the company's business activity through research before generating work.")
    saved = store.get_workspace(tenant_id, lead_id=lead_id)
    if saved and saved.automation and saved.automation.worker_id == _worker_id and saved.automation.status in {"queued", "running"}:
        return saved
    workspace = reconcile_workspace(store, lead)
    from agents.company_brief import brief_current
    from agents.investment_case import case_current
    from agents.analyst_pack import VERSION, current_pack, validate_saved_sections
    if analyst:
        validate_saved_sections(workspace.analyst_pack)
    if analyst and not refresh and not analyst_model and current_pack(workspace) and workspace.analyst_pack.get('status') == 'complete':
        return workspace
    if not analyst and not refresh and ((readiness and case_current(workspace) and workspace.investment_case.get("status")=="complete") or (not readiness and ((brief and brief_current(workspace) and workspace.company_brief.get('status')!='needs_review') or (not brief and workspace.draft_status == "draft" and workspace.draft_basis_hash == workspace.basis_hash)))):
        return workspace
    pending = [w for w in store.list_workspaces(tenant_id) if w.automation and w.automation.worker_id == _worker_id and w.automation.status in {"queued", "running"}]
    if len(pending) >= 3:
        raise HTTPException(429, "Three company jobs are already queued. Your existing work is saved; wait for one to finish.")
    if analyst and not analyst_model and workspace.analyst_pack.get('version')==VERSION and workspace.analyst_pack.get('generation_config',{}).get('mode')=='model_authored_v1':
        analyst_model=workspace.analyst_pack['generation_config']['model']
        analyst_review_model=workspace.analyst_pack['generation_config'].get('review_model')
        analyst_review_thinking=workspace.analyst_pack['generation_config'].get('review_thinking')
        analyst_thinking=workspace.analyst_pack['generation_config'].get('thinking',False)
    from agents.local_models import shared_model_name
    workspace.automation = AutomationRun(model=(analyst_model if analyst_model and analyst_model!='auto' else shared_model_name(LocalModel()) if analyst else LocalModel().name), worker_id=_worker_id,
        phase="Starting company preparation")
    workspace.events.append({"at": utcnow(), "action": "automation_started", "detail": "Company investment preparation queued." if readiness else "Company brief queued." if brief else "Company operating plans queued."})
    store.save_workspace(workspace, expected_revision=workspace.revision)
    background.add_task(_prepare_job, store.db_path, tenant_id, lead_id, workspace.automation.id, brief, refresh=refresh, readiness=readiness, analyst=analyst, analyst_model=analyst_model, analyst_thinking=analyst_thinking, analyst_review_model=analyst_review_model, analyst_review_thinking=analyst_review_thinking)
    return workspace



@router.post("/leads/{lead_id}/evaluate")
def evaluate(lead_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    lead = store.get_lead(tenant_id, lead_id)
    if not lead: raise HTTPException(404, "Lead not found")
    try: return reconcile_workspace(store, lead)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/leads/{lead_id}/prepare")
def prepare(lead_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    lead = store.get_lead(tenant_id, lead_id)
    if not lead: raise HTTPException(404, "Lead not found")
    try:
        from agents.analyst_pack import prepare_analyst_pack
        return prepare_analyst_pack(store, lead)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    except Exception as exc: raise HTTPException(503, f"Local draft preparation unavailable ({type(exc).__name__}); saved evidence and controls retained.") from exc


class AttestationRequest(BaseModel):
    kind: Literal["source_rights_review", "identity_review", "engagement_authority", "regulatory_scope", "privacy_basis", "commercial_validation",
                  "financial_review", "incubation_outcomes", "investor_qualification", "release_approval", "signed_documents", "funds_received"]
    note: str = Field(min_length=12, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    expected_revision: int


@router.post("/workspaces/{workspace_id}/attestations")
def attest(workspace_id: str, body: AttestationRequest, store: Store = Depends(get_store),
           tenant_id: str = Depends(get_tenant_id), reviewer: str = Depends(get_reviewer)):
    workspace = store.get_workspace(tenant_id, workspace_id=workspace_id)
    if not workspace: raise HTTPException(404, "Workspace not found")
    if workspace.revision != body.expected_revision: raise HTTPException(409, "Workspace changed; reload before recording a review.")
    lead = store.get_lead(tenant_id, workspace.lead_id)
    basis, valid, documents, extraction = workspace_basis(store, lead)
    if basis != workspace.basis_hash: raise HTTPException(409, "Evidence changed; evaluate the workspace before recording a review.")
    if not set(body.evidence_ids).issubset(valid): raise HTTPException(422, "Evidence references must belong to this company/workspace.")
    if body.kind != "identity_review" and not any(e.startswith("doc:") for e in body.evidence_ids):
        raise HTTPException(422, "This review requires a supporting company document; public company claims alone do not satisfy it.")
    if body.kind == "financial_review":
        from agents.review_checkpoint import is_ready_for_compilation
        if extraction is None or not is_ready_for_compilation(extraction):
            raise HTTPException(409, "The existing financial extraction/review checks must pass first.")
    if body.kind == "release_approval" and (workspace.draft_status != "draft" or workspace.draft_basis_hash != basis):
        raise HTTPException(409, "Prepare a current draft pack before recording release review.")
    workspace.attestations.append(WorkspaceAttestation(**body.model_dump(exclude={"expected_revision"}), reviewer=reviewer, basis_hash=basis))
    workspace.events.append({"at": utcnow(), "action": "review_recorded", "detail": f"{body.kind} recorded by {reviewer}; company evidence version {basis[:12]}."})
    try: store.save_workspace(workspace, expected_revision=body.expected_revision)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    return reconcile_workspace(store, lead)


@router.post("/workspaces/{workspace_id}/execute/{action}")
def external_action(workspace_id: str, action: Literal["send", "sign", "transfer"],
                    store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    if not store.get_workspace(tenant_id, workspace_id=workspace_id): raise HTTPException(404, "Workspace not found")
    raise HTTPException(409, "External execution is disabled in this local pilot. A draft or attestation cannot authorize sending, signing or moving funds.")
