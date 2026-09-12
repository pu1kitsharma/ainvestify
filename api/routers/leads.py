"""
Sourcing & leads endpoints (plan §2/§3, milestone 3): source candidates,
review (keep/dismiss), promote to a real deal.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from agents.planner_agent import promote_lead_to_deal, source_ib_targets, source_leads
from agents.review_checkpoint import apply_lead_decision
from api.deps import get_reviewer, get_store, get_tenant_id
from api.models import LeadDecisionRequest, PromoteLeadRequest, SourceLeadsRequest
from schemas import Deal, SourcedLead
from store import Store

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.post("/source", response_model=list[SourcedLead])
def source(
    body: SourceLeadsRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    """VC-style sourcing (agents/sourcing_agent.discover_leads): early-stage
    candidates via GitHub/HN recency signals."""
    return source_leads(store, tenant_id, body.sector_keyword, location_filter=body.location_filter)


@router.post("/source-ib", response_model=list[SourcedLead])
def source_ib(
    body: SourceLeadsRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    """IB-style sourcing (agents/sourcing_agent.discover_ib_targets): mature/
    public companies signaling a transaction window via SEC filings."""
    return source_ib_targets(store, tenant_id, body.sector_keyword)


@router.get("", response_model=list[SourcedLead])
def list_leads(
    status: Optional[str] = None,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    return store.list_leads(tenant_id, status=status)


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
