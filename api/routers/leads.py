"""
Sourcing & leads endpoints (plan §2/§3, milestone 3): source candidates,
review (keep/dismiss), promote to a real deal.
"""
from typing import Optional
import uuid
from threading import BoundedSemaphore

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from agents.planner_agent import promote_lead_to_deal, source_ib_targets, source_leads
from agents.review_checkpoint import apply_lead_decision
from api.deps import get_reviewer, get_store, get_tenant_id
from api.models import LeadDecisionRequest, PromoteLeadRequest, SourceLeadsRequest, WebSourceRequest
from schemas import Deal, SourcedLead, WebSourcingRun, utcnow
from agents.authored_discovery import source_companies
from agents.local_models import LocalModel
from store import Store

router = APIRouter(prefix="/api/leads", tags=["leads"])

# Local CPU pilot: one web/model run per process. Durable results, bounded jobs;
# a process restart marks unfinished work interrupted, never silently successful.
_web_slot = BoundedSemaphore(1)
_worker_id = uuid.uuid4().hex


def _run_web_job(db_path, run, body):
    prepared_lead = None
    try:
        with Store(db_path) as store:
            result = source_companies(store, run, max_pages=body.max_pages, max_companies=body.max_companies)
            if body.prepare_workflow and result.lead_ids and result.status != 'cancelled':
                prepared_lead = result.lead_ids[0]
    except Exception as exc:
        with Store(db_path) as store:
            run.status = "failed"
            run.error = f"Local worker failed ({type(exc).__name__})."
            run.completed_at = utcnow()
            store.save_web_run(run)
    finally:
        _web_slot.release()
    if prepared_lead:
        # One automatic first draft; never fan out into unbounded inference.
        from api.routers.operations import _queue_prepare
        tasks = BackgroundTasks()
        try:
            with Store(db_path) as store:
                _queue_prepare(prepared_lead,tasks,store,run.tenant_id,analyst=True)
                saved = store.get_web_run(run.tenant_id,run.id)
                saved.generation_config['automatic_preparation_lead_id'] = prepared_lead
                store.save_web_run(saved)
            for task in tasks.tasks:
                task.func(*task.args, **task.kwargs)
        except Exception as exc:
            with Store(db_path) as store:
                saved = store.get_web_run(run.tenant_id,run.id)
                saved.warnings.append(f'Automatic company preparation could not start ({type(exc).__name__}). Source results are retained.')
                store.save_web_run(saved)


@router.post("/web-runs", response_model=WebSourcingRun, status_code=202)
def start_web_run(body: WebSourceRequest, background: BackgroundTasks,
                  store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    if not _web_slot.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A discovery search is already running. Company preparation can continue alongside it.")
    try:
        run = WebSourcingRun(tenant_id=tenant_id, thesis=body.thesis, geography=body.geography,
                            seed_urls=body.seed_urls, model=LocalModel().name, worker_id=_worker_id)
        store.save_web_run(run)
        background.add_task(_run_web_job, store.db_path, run, body)
        return run
    except Exception:
        _web_slot.release()
        raise


def _recover_run(store, run):
    if run.status in {"running", "cancel_requested"} and run.worker_id != _worker_id:
        run.status = "interrupted"
        run.error = "The local worker restarted. Start a new run to continue research; saved leads are retained."
        run.completed_at = utcnow()
        store.save_web_run(run)
    return run


@router.get("/web-runs", response_model=list[WebSourcingRun], response_model_exclude={"__all__": {"company_profiles"}})
def list_web_runs(store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    return [_recover_run(store, run) for run in store.list_web_runs(tenant_id)]


@router.get("/web-runs/{run_id}", response_model=WebSourcingRun)
def get_web_run(run_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    run = store.get_web_run(tenant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return _recover_run(store, run)


@router.post("/web-runs/{run_id}/cancel", response_model=WebSourcingRun)
def cancel_web_run(run_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    run = store.get_web_run(tenant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    run = _recover_run(store, run)
    if run.status == "running":
        run.status = "cancel_requested"
        store.save_web_run(run)
    return run


@router.get("/web-runs/{run_id}/leads", response_model=list[SourcedLead])
def web_run_leads(run_id: str, store: Store = Depends(get_store), tenant_id: str = Depends(get_tenant_id)):
    run = store.get_web_run(tenant_id, run_id)
    if run is None:
        raise HTTPException(404, "Research run not found")
    snapshots = {profile.id: profile for profile in run.company_profiles}
    result = []
    for lead_id in run.lead_ids:
        lead = store.get_lead(tenant_id, lead_id)
        if lead:
            profile = snapshots.get(lead.company_id)
            if profile:
                lead = lead.model_copy(update={"company_profile": profile, "company_name": profile.name})
            result.append(lead)
    return result


@router.post("/source", response_model=list[SourcedLead])
def source(
    body: SourceLeadsRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    """VC-style sourcing (agents/sourcing_agent.discover_leads): early-stage
    candidates via GitHub/HN recency signals."""
    raise HTTPException(410, 'Use /api/leads/web-runs for model-driven company discovery.')


@router.post("/source-ib", response_model=list[SourcedLead])
def source_ib(
    body: SourceLeadsRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    """IB-style sourcing (agents/sourcing_agent.discover_ib_targets): mature/
    public companies signaling a transaction window via SEC filings."""
    raise HTTPException(410, 'Use /api/leads/web-runs for model-driven company discovery.')


@router.get("", response_model=list[SourcedLead])
def list_leads(
    status: Optional[str] = None,
    web_run_only: bool = False,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    return store.list_leads(tenant_id, status=status, web_run_only=web_run_only)


@router.get("/{lead_id}", response_model=SourcedLead)
def get_lead(
    lead_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    lead = store.get_lead(tenant_id, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/decision", response_model=SourcedLead)
def decide_lead(
    lead_id: str,
    body: LeadDecisionRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    lead = store.get_lead(tenant_id, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if body.decision not in ("keep", "dismiss"):
        raise HTTPException(status_code=400, detail="decision must be 'keep' or 'dismiss'")

    event = apply_lead_decision(lead, reviewer, body.decision)
    store.save_lead(lead)
    store.append_audit_events([event])
    return lead


@router.post("/{lead_id}/promote", response_model=Deal)
def promote(
    lead_id: str,
    body: PromoteLeadRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    lead = store.get_lead(tenant_id, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return promote_lead_to_deal(store, lead, name=body.name)
