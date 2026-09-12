"""
Deal lifecycle write endpoints (plan §2/§3, milestone 3): create, sign
mandate, upload a document (ingestion), extract, audit log. GET list/detail
live in api/routers/dashboard.py (milestone 2); review decisions live in
api/routers/review.py.

Uploaded files are saved under uploads/{deal_id}/ (plan §2) -- local disk,
same as the CLI's document_path convention, just written by the API instead
of typed at a prompt.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from agents.planner_agent import _run_extract, _run_ingest, apply_sign_mandate, start_deal
from api.deps import get_store, get_tenant_id
from api.models import CreateDealRequest, ExtractRequest, SignMandateRequest
from schemas import AuditEvent, Deal, ExtractionResult
from store import Store

router = APIRouter(prefix="/api/deals", tags=["deals"])

UPLOAD_ROOT = Path(__file__).parent.parent.parent / "uploads"


def _get_deal_or_404(store: Store, tenant_id: str, deal_id: str) -> Deal:
    deal = store.get_deal(tenant_id, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.post("", response_model=Deal)
def create_deal(
    body: CreateDealRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    return start_deal(store, tenant_id=tenant_id, name=body.name, stage=body.stage)


@router.post("/{deal_id}/mandate", response_model=Deal)
def sign_mandate(
    deal_id: str,
    body: SignMandateRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    return apply_sign_mandate(store, deal, body.mandate_type, body.terms_summary)


@router.post("/{deal_id}/documents", response_model=Deal)
def upload_document(
    deal_id: str,
    file: UploadFile = File(...),
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    # Deliberately sync, not async: get_store is a sync generator dependency
    # that FastAPI resolves in a worker thread, but an `async def` endpoint
    # body runs on the event-loop thread instead -- handing that Store's
    # sqlite3 connection across those two different threads raises
    # "objects created in a thread can only be used in that same thread."
    # Keeping this sync (like every other endpoint here) means the
    # dependency and the handler body run in the same worker thread.
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    if not file.filename or Path(file.filename).suffix.lower() not in (".pdf", ".xlsx", ".xlsm"):
        raise HTTPException(status_code=400, detail="Only .pdf/.xlsx/.xlsm documents are supported")

    deal_dir = UPLOAD_ROOT / deal_id
    deal_dir.mkdir(parents=True, exist_ok=True)
    dest = deal_dir / file.filename
    dest.write_bytes(file.file.read())

    _run_ingest(store, deal, str(dest))
    return store.get_deal(tenant_id, deal_id)


@router.post("/{deal_id}/extract", response_model=ExtractionResult)
def run_extract(
    deal_id: str,
    body: ExtractRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = _get_deal_or_404(store, tenant_id, deal_id)
    try:
        return _run_extract(store, deal, body.model, reviewer_feedback=body.reviewer_feedback)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{deal_id}/audit-log", response_model=list[AuditEvent])
def get_audit_log(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    _get_deal_or_404(store, tenant_id, deal_id)
    return store.get_audit_log(tenant_id, deal_id)
