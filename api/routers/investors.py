"""
Investor / demand-book endpoints (plan §2, folded into milestone 3 since
apply_add_investor was already a pure function from Milestone 1 and this is
part of the deal-lifecycle state machine's REVIEWED-state surface, not a
separate milestone). Pure record-keeping only -- no endpoint here contacts
anyone, matching the same boundary CLAUDE.md states for sourcing.
"""
from fastapi import APIRouter, Depends, HTTPException

from agents.planner_agent import apply_add_investor
from api.deps import get_store, get_tenant_id
from api.models import AddInvestorRequest
from schemas import InvestorContact
from store import Store

router = APIRouter(prefix="/api/deals", tags=["investors"])


@router.post("/{deal_id}/investors", response_model=InvestorContact)
def add_investor(
    deal_id: str,
    body: AddInvestorRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = store.get_deal(tenant_id, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return apply_add_investor(
        store, deal, body.investor_name, firm=body.firm,
        nda_status=body.nda_status, interest_level=body.interest_level, notes=body.notes,
    )


@router.get("/{deal_id}/investors", response_model=list[InvestorContact])
def list_investors(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    if store.get_deal(tenant_id, deal_id) is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return store.get_investor_contacts(tenant_id, deal_id)
