"""
Compilation endpoints (plan §2/§4, milestone 4): compile the CIM; the
teaser's two-step draft + safe-to-send confirm; the pro-forma with an
optional growth-rate override; rerun analytics; fetch the document suite.

Every write here delegates to the pure functions agents/planner_agent.py
and agents/compilation_agent.py already built (Milestones 1 and 4) -- no
compilation/anonymization logic lives in this file.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.compilation_agent import CompilationBlockedError
from agents.planner_agent import (
    _run_compile,
    _run_rerun_analytics,
    apply_compile_proforma,
    confirm_teaser_safe_to_send,
    generate_teaser_draft,
)
from api.deps import get_reviewer, get_store, get_tenant_id
from schemas import ChartArtifact, Deal, MemoVersion
from store import Store

router = APIRouter(prefix="/api/deals", tags=["compilation"])


class TeaserDraftRequest(BaseModel):
    business_description: str


class TeaserConfirmRequest(BaseModel):
    confirmed: bool


class ProformaRequest(BaseModel):
    growth_rate_override: Optional[float] = None


def _get_deal_or_404(store: Store, tenant_id: str, deal_id: str) -> Deal:
    deal = store.get_deal(tenant_id, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


def _current_release_status(store: Store, tenant_id: str, deal_id: str, versions: list[MemoVersion]):
    """Show effective approval, preserving the original review in storage."""
    lead = store.get_lead_by_promoted_deal_id(tenant_id, deal_id)
    if not lead or not store.get_workspace(tenant_id, lead_id=lead.id):
        return versions
    from agents.operating_workflow import reconcile_workspace

    workspace = reconcile_workspace(store, lead, persist=False)
    ready = next(item for item in workspace.work_items if item.id == "release").status == "completed"
    return [memo.model_copy(update={"approved_by": None})
            if memo.document_type == "teaser" and memo.approved_by and
            (not ready or memo.approval_basis_hash != workspace.basis_hash) else memo for memo in versions]


@router.post("/{deal_id}/compile/cim", response_model=MemoVersion)
def compile_cim_endpoint(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    try:
        return _run_compile(store, deal)
    except CompilationBlockedError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{deal_id}/compile/teaser/draft", response_model=MemoVersion)
def compile_teaser_draft_endpoint(
    deal_id: str,
    body: TeaserDraftRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    try:
        return generate_teaser_draft(store, deal, body.business_description)
    except CompilationBlockedError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{deal_id}/compile/teaser/{memo_id}/confirm", response_model=MemoVersion)
def confirm_teaser_endpoint(
    deal_id: str,
    memo_id: str,
    body: TeaserConfirmRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    _get_deal_or_404(store, tenant_id, deal_id)
    deal = store.get_deal(tenant_id, deal_id)
    try:
        return confirm_teaser_safe_to_send(store, deal, memo_id, reviewer, confirmed=body.confirmed)
    except CompilationBlockedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{deal_id}/compile/proforma", response_model=MemoVersion)
def compile_proforma_endpoint(
    deal_id: str,
    body: ProformaRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    try:
        return apply_compile_proforma(store, deal, reviewer, growth_rate_override=body.growth_rate_override)
    except CompilationBlockedError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{deal_id}/analytics/rerun", response_model=list[ChartArtifact])
def rerun_analytics_endpoint(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    return _run_rerun_analytics(store, deal)


@router.get("/{deal_id}/documents", response_model=list[MemoVersion])
def list_documents(
    deal_id: str,
    document_type: Optional[str] = None,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    """The document suite (plan §2): every version of every document type
    by default, or every version of one type via ?document_type=teaser."""
    _get_deal_or_404(store, tenant_id, deal_id)
    versions = store.get_memo_versions(tenant_id, deal_id)
    if document_type is not None:
        versions = [v for v in versions if v.document_type == document_type]
    return _current_release_status(store, tenant_id, deal_id, versions)


@router.get("/{deal_id}/documents/latest", response_model=MemoVersion)
def get_latest_document(
    deal_id: str,
    document_type: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    _get_deal_or_404(store, tenant_id, deal_id)
    memo = store.get_latest_memo_version(tenant_id, deal_id, document_type)
    if memo is None:
        raise HTTPException(status_code=404, detail=f"No {document_type!r} document for this deal yet")
    return _current_release_status(store, tenant_id, deal_id, [memo])[0]
