"""
Review endpoints (plan §2 GET, §3 decisions/milestone 3). Every write here
delegates to the same pure apply_*/recompute_* functions review_checkpoint.py
built for the CLI in Milestone 1 -- one decision per HTTP request, in place
of one iteration of the CLI's input() loop.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from agents.extraction_agent import extract
from agents.review_checkpoint import (
    apply_cap_table_decision,
    apply_field_decision,
    apply_funding_history_decision,
    is_ready_for_compilation,
    recompute_deal_review_status,
)
from api.deps import get_reviewer, get_store, get_tenant_id
from api.models import BlockDecisionRequest, FieldDecisionRequest, FieldDecisionResponse, ReviewPayload
from schemas import Document
from store import Store

router = APIRouter(prefix="/api/deals", tags=["review"])


@router.get("/{deal_id}/review", response_model=ReviewPayload)
def get_review(
    deal_id: str,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    if store.get_deal(tenant_id, deal_id) is None:
        raise HTTPException(status_code=404, detail="Deal not found")

    result = store.get_extraction_result(tenant_id, deal_id)
    return ReviewPayload(
        extraction_result=result,
        ready_for_compilation=is_ready_for_compilation(result) if result else False,
        cross_check_flags=result.cross_check_flags if result else [],
    )


def _load_deal_and_result(store: Store, tenant_id: str, deal_id: str):
    deal = store.get_deal(tenant_id, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    result, raw = store.get_extraction_result_with_raw(tenant_id, deal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No extraction result for this deal yet")
    return deal, result, raw


def _first_document(store: Store, tenant_id: str, deal_id: str) -> Optional[Document]:
    documents = store.get_documents_for_deal(tenant_id, deal_id)
    return documents[0] if documents else None


def _persist_and_respond(store: Store, deal, result, raw_before, outcome) -> FieldDecisionResponse:
    # Compare-and-swap, not a plain save: two review decisions on the same
    # deal (even on different fields) racing this same read-mutate-write
    # sequence would otherwise be a last-write-wins loss of whichever
    # commits first -- and unlike agents/planner_agent._run_ingest's
    # document_ids race, this can't be closed with a held write lock
    # (store.update_deal's BEGIN IMMEDIATE) because a reject decision can
    # run a real multi-minute Ollama re-extraction (apply_field_decision's
    # retry_extraction) -- holding SQLite's write lock that long would
    # block every other write in the database, not just this deal's.
    if not store.save_extraction_result_if_unchanged(result, raw_before):
        raise HTTPException(
            status_code=409,
            detail="This deal's review data changed while processing your request -- refresh and try again.",
        )
    store.append_audit_events(outcome.audit_events)
    if outcome.resolved:
        new_status = recompute_deal_review_status(result)
        updated_deal = store.update_deal(deal.tenant_id, deal.id, lambda d: setattr(d, "status", new_status))
        deal = updated_deal or deal
    return FieldDecisionResponse(outcome=outcome, extraction_result=result, deal=deal)


@router.post("/{deal_id}/review/fields/{field_name}", response_model=FieldDecisionResponse)
def decide_field(
    deal_id: str,
    field_name: str,
    body: FieldDecisionRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    deal, result, raw_before = _load_deal_and_result(store, tenant_id, deal_id)
    if not hasattr(result, field_name):
        raise HTTPException(status_code=404, detail=f"No such field {field_name!r}")
    document = _first_document(store, tenant_id, deal_id)

    def retry_fn(doc, note):
        return extract(doc, model=body.model, reviewer_feedback=note)

    try:
        outcome = apply_field_decision(
            result, field_name, reviewer, body.decision,
            new_value=body.new_value, note=body.note,
            document=document, retry_extraction=retry_fn,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _persist_and_respond(store, deal, result, raw_before, outcome)


@router.post("/{deal_id}/review/cap-table", response_model=FieldDecisionResponse)
def decide_cap_table(
    deal_id: str,
    body: BlockDecisionRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    deal, result, raw_before = _load_deal_and_result(store, tenant_id, deal_id)
    document = _first_document(store, tenant_id, deal_id)

    def retry_fn(doc, note):
        return extract(doc, model=body.model, reviewer_feedback=note)

    try:
        outcome = apply_cap_table_decision(
            result, reviewer, body.decision, note=body.note,
            document=document, retry_extraction=retry_fn,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _persist_and_respond(store, deal, result, raw_before, outcome)


@router.post("/{deal_id}/review/funding-history", response_model=FieldDecisionResponse)
def decide_funding_history(
    deal_id: str,
    body: BlockDecisionRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
    reviewer: str = Depends(get_reviewer),
):
    deal, result, raw_before = _load_deal_and_result(store, tenant_id, deal_id)
    document = _first_document(store, tenant_id, deal_id)

    def retry_fn(doc, note):
        return extract(doc, model=body.model, reviewer_feedback=note)

    try:
        outcome = apply_funding_history_decision(
            result, reviewer, body.decision, note=body.note,
            document=document, retry_extraction=retry_fn,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _persist_and_respond(store, deal, result, raw_before, outcome)
