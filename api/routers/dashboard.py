"""
Dashboard endpoints (plan §2/§3, milestone 2): deal summaries, read-only.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_store, get_tenant_id
from schemas import Deal, DealSummary
from store import Store

router = APIRouter(prefix="/api/deals", tags=["dashboard"])


@router.get("", response_model=list[DealSummary])
def list_deals(
    status: Optional[str] = None,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    return store.list_deals_with_summary(tenant_id, status=status)


@router.get("/{deal_id}", response_model=Deal)
def get_deal(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = store.get_deal(tenant_id, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
