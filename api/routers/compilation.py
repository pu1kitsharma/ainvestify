"""Historical deal documents remain readable; template generation is retired."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.core.planner_agent import _run_rerun_analytics
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
    versions=[memo.model_copy(deep=True) for memo in versions]
    for memo in versions:
        if memo.structured_data:
            for index,chart in enumerate(memo.structured_data.get('charts',[])):
                chart['storage_uri']=f'api/deals/{deal_id}/legacy-charts/{memo.id}/{index}'
    lead = store.get_lead_by_promoted_deal_id(tenant_id, deal_id)
    if not lead or not store.get_workspace(tenant_id, lead_id=lead.id):
        return versions
    from agents.analysis.operating_workflow import reconcile_workspace

    workspace = reconcile_workspace(store, lead, persist=False)
    release = next((item for item in workspace.work_items if item.id == "release"), None)
    ready = release is not None and release.status == "completed"
    return [memo.model_copy(update={"approved_by": None})
            if memo.document_type == "teaser" and memo.approved_by and
            (not ready or memo.approval_basis_hash != workspace.basis_hash) else memo for memo in versions]


@router.post("/{deal_id}/compile/cim", response_model=MemoVersion)
def compile_cim_endpoint(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    raise HTTPException(410, 'Legacy CIM templates are retired. Open the deal room for local-model materials and exact-artifact validation.')


@router.post("/{deal_id}/compile/teaser/draft", response_model=MemoVersion)
def compile_teaser_draft_endpoint(
    deal_id: str,
    body: TeaserDraftRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    raise HTTPException(410, 'Legacy teaser templates are retired. Open the deal room for local-model materials and exact-artifact validation.')


@router.post("/{deal_id}/compile/teaser/{memo_id}/confirm", response_model=MemoVersion)
def confirm_teaser_endpoint(
    deal_id: str,
    memo_id: str,
    body: TeaserConfirmRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    raise HTTPException(410, 'Legacy teaser release is retired. Use exact-version validation and review in the deal room.')


@router.post("/{deal_id}/compile/proforma", response_model=MemoVersion)
def compile_proforma_endpoint(
    deal_id: str,
    body: ProformaRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    raise HTTPException(410, 'Legacy pro forma templates are retired. Open the deal room for validated financial inputs and local-model materials.')


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


@router.get('/{deal_id}/legacy-charts/{memo_id}/{chart_index}')
def legacy_chart(deal_id: str,memo_id: str,chart_index: int,store: Store=Depends(get_store),tenant_id: str=Depends(get_tenant_id)):
    from pathlib import Path
    import os
    from fastapi.responses import Response
    _get_deal_or_404(store,tenant_id,deal_id)
    memo=store.get_memo_version(tenant_id,memo_id)
    charts=(memo.structured_data or {}).get('charts',[]) if memo and memo.deal_id==deal_id else []
    if chart_index<0 or chart_index>=len(charts):raise HTTPException(404,'Chart not found')
    root=Path(__file__).resolve().parents[2]
    allowed=root/'memo_output'/deal_id
    path=root/charts[chart_index]['storage_uri']
    if path.is_symlink() or allowed.is_symlink() or path.resolve()!=path.absolute() or allowed not in path.parents or path.suffix.lower()!='.png':
        raise HTTPException(404,'Chart not available')
    try:
        fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as source:content=source.read(8*1024*1024+1)
        if len(content)>8*1024*1024 or not content.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError()
    except (OSError,ValueError):raise HTTPException(404,'Chart not available')
    return Response(content,media_type='image/png',headers={'X-Artifact-State':'legacy-preview'})
