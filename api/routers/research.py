"""Read/review historical findings; new research runs use the deal room."""
from fastapi import APIRouter, Depends, HTTPException

from agents.core.planner_agent import mark_research_reviewed
from agents.core.review_checkpoint import apply_finding_decision
from api.deps import get_reviewer, get_store, get_tenant_id
from api.models import FindingDecisionRequest, RunResearchRequest
from schemas import Deal, ResearchFinding
from store import Store

router = APIRouter(prefix="/api/deals", tags=["research"])


def _get_deal_or_404(store: Store, tenant_id: str, deal_id: str) -> Deal:
    deal = store.get_deal(tenant_id, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.post("/{deal_id}/research/run", response_model=list[ResearchFinding])
def run_research(
    deal_id: str,
    body: RunResearchRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    raise HTTPException(410, 'Legacy connector research is retired. Open the deal room for local-model, evidence-bound research.')


@router.get("/{deal_id}/research", response_model=list[ResearchFinding])
def list_research(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    _get_deal_or_404(store, tenant_id, deal_id)
    return store.get_research_findings(tenant_id, deal_id)


@router.post("/{deal_id}/research/{finding_id}/decision", response_model=ResearchFinding)
def decide_finding(
    deal_id: str,
    finding_id: str,
    body: FindingDecisionRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    _get_deal_or_404(store, tenant_id, deal_id)
    findings = store.get_research_findings(tenant_id, deal_id)
    finding = next((f for f in findings if f.id == finding_id), None)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    event = apply_finding_decision(finding, reviewer, body.decision)
    store.save_research_findings([finding])
    store.append_audit_events([event])
    return finding


@router.post("/{deal_id}/research/mark-reviewed", response_model=Deal)
def mark_reviewed(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    return mark_research_reviewed(store, deal)
