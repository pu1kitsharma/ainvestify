"""Deal-room facade over OperatingWorkspace, durable activation and private artifacts."""
from __future__ import annotations
import hashlib
import json
import os
from urllib.parse import urlsplit
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from api.deps import get_identity, get_store
from agents.analysis.operating_workflow import reconcile_workspace
from delivery import jobs
from delivery.artifacts import get_artifact, artifact_bytes
from delivery.room_mapping import plan_room_mapping
from delivery.workflow_contracts import DealRoomActivated
from agents.core.planner_agent import lock_lead
from schemas import CompanyProfile, SourcedLead, new_id

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def document_input_version(document):
    """Bind source bytes and recorded ingestion, not just a mutable path label."""
    from delivery.storage import read_source_bytes
    metadata=document.model_dump(exclude={'uploaded_at'})
    try:
        content=read_source_bytes(document.storage_uri)
        source={'sha256':hashlib.sha256(content).hexdigest(),'size_bytes':len(content)}
    except (OSError,ValueError):
        source={'state':'unavailable_or_unsafe'}
    return {'record':metadata,'source':source}


def revision_for(store, workspace):
    from agents.inference.local_models import PreparationModel,shared_model_name
    lead = store.get_lead(workspace.tenant_id, workspace.lead_id)
    if not lead:
        raise ValueError("Room company unavailable")
    # Stable on reopen: exclude timestamps/revisions and derived job/render output.
    profile = lead.company_profile.model_dump(exclude={"updated_at"}) if lead.company_profile else None
    documents = store.get_documents_for_deal(workspace.tenant_id, workspace.deal_id) if workspace.deal_id else []
    if workspace.deal_id and lead.promoted_deal_id!=workspace.deal_id:
        raise ValueError('Room association changed; reconcile before processing')
    extraction=store.get_extraction_result(workspace.tenant_id,workspace.deal_id) if workspace.deal_id else None
    selected_model = shared_model_name(PreparationModel())
    draft_model = os.environ.get('LOCAL_MEMO_DRAFT_MODEL', 'qwen3.5:9b')
    payload = {"profile":profile,"deal_id":workspace.deal_id,"promoted_deal_id":lead.promoted_deal_id,"metrics":workspace.metric_updates,
        "documents":[document_input_version(d) for d in sorted(documents,key=lambda item:item.id)],
        "extraction":extraction.model_dump() if extraction else None,
        "analysis_inputs":workspace.company_analysis.get("inputs",{}),
        "metric_imports":[{k:item.get(k) for k in ('id','source_name','text')} for item in workspace.metric_imports],
        "workflow_contract":"room-v26-bounded-review-revision","local_model":selected_model,
        "memo_draft_model":draft_model,"memo_draft_b_model":os.environ.get('LOCAL_MEMO_PART_B_MODEL', draft_model),
        "memo_draft_token_cap":1400,
        "memo_correction_model":selected_model,"memo_correction_token_cap":1500,
        "memo_prose_model":selected_model,"memo_prose_token_cap":1000,
        "memo_review_model":os.environ.get('LOCAL_MEMO_REVIEW_MODEL', selected_model),
        "memo_review_token_cap":1500,"memo_calls_per_pass":5,
        "memo_validation_contract":"source-bound-v2"}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()


def activate(store, identity, lead_id):
    lead = store.get_lead(identity.tenant_id,lead_id)
    if not lead or not lead.company_profile:
        raise HTTPException(404,"Company with a profile not found")
    deal = store.get_deal(identity.tenant_id,lead.promoted_deal_id) if lead.promoted_deal_id else None
    if deal is None or not deal.mandate_signed_at:
        raise HTTPException(409,"Lock the company before preparing investor materials.")
    workspace = store.get_workspace(identity.tenant_id,lead_id=lead_id)
    if workspace is None:
        try:
            workspace = reconcile_workspace(store,lead)
        except Exception as exc:
            # A concurrent first activation may have won the unique lead slot.
            workspace = store.get_workspace(identity.tenant_id,lead_id=lead_id)
            if workspace is None:
                raise HTTPException(409,"Room creation conflicted; retry") from exc
    mappings = plan_room_mapping(identity.tenant_id,store.list_workspaces(identity.tenant_id),
        store.list_leads(identity.tenant_id),store.list_deals(identity.tenant_id))
    mapping = next(m for m in mappings if m.workspace_id == workspace.id)
    if mapping.state == "conflict":
        raise HTTPException(409,"Room relationship needs reconciliation: " + mapping.reason)
    expected_deal = mapping.deal_id if mapping.state == "link_candidate" else None
    if workspace.deal_id and workspace.deal_id != expected_deal:
        raise HTTPException(409,"Existing room association conflicts with the promoted lead")
    if expected_deal and workspace.deal_id is None:
        workspace.deal_id = expected_deal
        store.save_workspace(workspace,expected_revision=workspace.revision)
    event = DealRoomActivated(tenant_id=identity.tenant_id,actor_id=identity.user_id,
        workspace_id=workspace.id,input_revision=revision_for(store,workspace),workflow_version="room-v26-bounded-review-revision")
    try:
        job = jobs.enqueue(store.conn,event)
    except (ValueError,PermissionError) as exc:
        raise HTTPException(409,str(exc))
    return {"workspace_id":workspace.id,"job":jobs.public_job(job)}


@router.post("/from-lead/{lead_id}/activate",status_code=202)
def activate_lead(lead_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    return activate(store,identity,lead_id)


@router.post("/from-public-kb/{source_id}/activate", status_code=202)
def activate_public_kb_source(source_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    """Import one indexed public company into this user's private sandbox."""
    from pathlib import Path
    from public_kb.ingestion import PublicIngestion
    from public_kb.room_seed import lead_from_indexed_source
    root = Path(__file__).resolve().parents[2] / "runtime_public_kb"
    if not (root / "kb.db").is_file():
        raise HTTPException(503, "Public KB is unavailable")
    kb = PublicIngestion(root / "kb.db", root / "archive")
    try:
        lead = lead_from_indexed_source(store, kb, source_id, identity.tenant_id)
    except (ValueError, KeyError, PermissionError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        kb.close()
    return dict(activate(store, identity, lead.id), lead_id=lead.id)


class DirectCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2,max_length=200)
    website: str = Field(min_length=8,max_length=500)
    # A company adding itself states its engagement terms; it is locked on entry.
    mandate_type: Literal["fundraising_advisory","incubation","sell_side_advisory"]
    terms_summary: str = Field(min_length=10,max_length=1000)


@router.post("",status_code=201)
def direct_company(body: DirectCompany,store=Depends(get_store),identity=Depends(get_identity)):
    parsed = urlsplit(body.website)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422,"Provide the company's public HTTPS website")
    website = f"https://{parsed.hostname.lower()}" + (f":{parsed.port}" if parsed.port else "") + parsed.path.rstrip("/")
    profile = store.get_company_by_website(identity.tenant_id,website)
    if profile is None:
        profile = CompanyProfile(tenant_id=identity.tenant_id,name=body.name,website=website,
            identity_status="unresolved",provenance={"origin":"manual","entered_by":identity.user_id})
        store.save_company(profile)
    leads = [l for l in store.list_leads(identity.tenant_id) if l.company_id == profile.id]
    if len(leads)>1:
        raise HTTPException(409,"Multiple company leads require reconciliation")
    if leads:
        lead = leads[0]
    else:
        lead = SourcedLead(tenant_id=identity.tenant_id,company_name=profile.name,
            company_id=profile.id,company_profile=profile)
        store.save_lead(lead)
    lock_lead(store,lead,body.mandate_type,body.terms_summary)
    return dict(activate(store,identity,lead.id),lead_id=lead.id)


def require_room(store,identity,room_id):
    room = store.get_workspace(identity.tenant_id,workspace_id=room_id)
    if room is None:
        raise HTTPException(404,"Room not found")
    return room


@router.get("/{room_id}")
def room_status(room_id: str,store=Depends(get_store),identity=Depends(get_identity)):
    room = require_room(store,identity,room_id)
    artifact_ids = store.conn.execute("SELECT id FROM room_artifacts WHERE tenant_id=? AND workspace_id=?",
        (identity.tenant_id,room_id)).fetchall()
    return {"id":room.id,"lead_id":room.lead_id,"deal_id":room.deal_id,
        "jobs":[jobs.public_job(j) for j in jobs.list_jobs(store.conn,identity.tenant_id,room.id)],
        "artifacts":[get_artifact(store.conn,identity.tenant_id,row[0]) for row in artifact_ids]}


@router.post("/{room_id}/jobs/{job_id}/cancel")
def cancel_job(room_id: str,job_id: str,store=Depends(get_store),identity=Depends(get_identity)):
    require_room(store,identity,room_id)
    if not any(j["id"]==job_id for j in jobs.list_jobs(store.conn,identity.tenant_id,room_id)):
        raise HTTPException(404,"Job not found")
    jobs.cancel(store.conn,identity.tenant_id,job_id)
    current=next(j for j in jobs.list_jobs(store.conn,identity.tenant_id,room_id) if j['id']==job_id)
    return {"state":current['state']}


@router.get("/{room_id}/artifacts/{artifact_id}/preview")
def preview(room_id: str,artifact_id: str,inline: bool = False,store=Depends(get_store),identity=Depends(get_identity)):
    require_room(store,identity,room_id)
    artifact = get_artifact(store.conn,identity.tenant_id,artifact_id)
    if not artifact or artifact["workspace_id"] != room_id:
        raise HTTPException(404,"Artifact not found")
    try:
        content = artifact_bytes(identity.tenant_id,artifact)
    except (OSError,ValueError):
        raise HTTPException(409,"Artifact integrity check failed")
    # A draft PDF may be shown in the browser's own viewer; every other format,
    # and any request without `inline`, stays an attachment.
    show_inline = inline and artifact["format"] == "pdf"
    return Response(content,media_type="application/pdf" if show_inline else "application/octet-stream",headers={
        "Content-Disposition":f'{"inline" if show_inline else "attachment"}; filename="DRAFT-{artifact_id}.{artifact["format"]}"',
        "X-Content-Type-Options":"nosniff","X-Artifact-State":"draft"})


@router.get("/{room_id}/artifacts/{artifact_id}/download")
def download(room_id: str,artifact_id: str,store=Depends(get_store),identity=Depends(get_identity)):
    require_room(store,identity,room_id)
    artifact = get_artifact(store.conn,identity.tenant_id,artifact_id)
    if not artifact or artifact["workspace_id"] != room_id:
        raise HTTPException(404,"Artifact not found")
    from delivery.release import load_package,evaluate_package
    for row in store.conn.execute("SELECT id FROM room_packages WHERE tenant_id=? AND workspace_id=? AND state='released'",
            (identity.tenant_id,room_id)).fetchall():
        manifest,_,_,_=load_package(store,identity.tenant_id,row[0])
        if not any(f.artifact_id==artifact_id for f in manifest.files):continue
        try:
            assessment=evaluate_package(store,identity.tenant_id,row[0])
            if assessment.eligible_for_release:
                content=artifact_bytes(identity.tenant_id,artifact)
                return Response(content,media_type='application/octet-stream',headers={
                    'Content-Disposition':f'attachment; filename="{artifact_id}.{artifact["format"]}"'})
        except (ValueError,OSError):
            continue
    raise HTTPException(409,"Final download blocked: mandatory package validation and reviews are incomplete or stale.")


@router.post('/{room_id}/validate')
def validate(room_id: str,store=Depends(get_store),identity=Depends(get_identity)):
    from delivery.release import validate_room
    room=require_room(store,identity,room_id)
    try:
        package_id,assessment=validate_room(store,identity.tenant_id,room)
        return {'package_id':package_id,**assessment.model_dump()}
    except (ValueError,OSError):
        raise HTTPException(409,'Artifact inspection or revision selection failed; preserve the files for review.')


@router.post('/{room_id}/packages/{package_id}/release')
def release(room_id: str,package_id: str,store=Depends(get_store),identity=Depends(get_identity)):
    from delivery.release import load_package,publish_package
    require_room(store,identity,room_id)
    if identity.role!='owner':raise HTTPException(403,'Only the sandbox owner can request release')
    try:
        manifest,_,_,_=load_package(store,identity.tenant_id,package_id)
        if manifest.workspace_id!=room_id:raise LookupError()
        return publish_package(store,identity.tenant_id,package_id)
    except LookupError:raise HTTPException(404,'Package not found')
    except (ValueError,OSError):raise HTTPException(409,'Mandatory validation and exact-version reviews block release')
