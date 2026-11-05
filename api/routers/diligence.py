"""Tenant-scoped internal diligence desk. No outbound delivery endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.deps import get_identity, get_store
from api.routers.rooms import require_room
from delivery.deal_documents import diligence as desk, runs

router = APIRouter(prefix='/api/rooms/{room_id}/diligence', tags=['diligence'])


def context(store, identity, room_id, write=False):
    room = require_room(store, identity, room_id)
    if write and identity.role != 'owner':
        raise HTTPException(403, 'Only the sandbox owner can update diligence records and approve answers')
    return room, runs.get(store.conn, identity.tenant_id, room_id)


def call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Link(Strict):
    evidence_id: str = Field(min_length=1, max_length=200)
    evidence_version: str = Field(pattern=r'^[a-f0-9]{64}$')


class Request(Strict):
    issue: str = Field(min_length=1, max_length=4000)
    required_record: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(default='', max_length=4000)
    origin: Literal['requirement', 'finding', 'question'] = 'requirement'
    owner: str = Field(default='', max_length=200)
    due_date: str | None = None
    priority: Literal['blocker', 'high', 'medium', 'low'] = 'high'
    status: Literal['open', 'in_progress', 'supplied', 'resolved'] = 'open'
    blocks: list[str] = Field(default_factory=list, max_length=100)
    accepted_evidence: list[Link] = Field(default_factory=list, max_length=100)
    acceptance_note: str = Field(default='', max_length=4000)
    expected_version: int = Field(default=0, ge=0)


@router.get('')
def overview(room_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    room, run = context(store, identity, room_id)
    investors = store.get_investor_contacts(identity.tenant_id, room.deal_id) if room.deal_id else []
    deal = store.get_deal(identity.tenant_id, room.deal_id) if room.deal_id else None
    requests = desk.request_view(store.conn, identity.tenant_id, room_id, run)
    return {'is_owner': identity.role == 'owner', 'requests': requests,
            'prioritized': sorted((r for r in requests if r['status'] != 'resolved'), key=lambda r: desk.PRIORITIES.index(r['priority']))[:10],
            'answers': desk.answer_view(store.conn, identity.tenant_id, room_id, run),
            'tracker': desk.process_view(store.conn, identity.tenant_id, room_id, run,
                [i.model_dump() for i in investors], {'purpose': deal.mandate_type, 'signed_at': deal.mandate_signed_at} if deal else None)}


@router.get('/evidence')
def evidence(room_id: str, scope: str = '', candidates: bool = False, store=Depends(get_store), identity=Depends(get_identity)):
    _, run = context(store, identity, room_id)
    return desk.evidence(store.conn, identity.tenant_id, room_id, run, scope, candidates and identity.role == 'owner')


@router.get('/history/{kind}')
def history(room_id: str, kind: Literal['request', 'answer', 'event', 'grant'], store=Depends(get_store), identity=Depends(get_identity)):
    context(store, identity, room_id)
    return desk.records(store.conn, identity.tenant_id, room_id, kind, history=True)


@router.post('/sync')
def sync(room_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    _, run = context(store, identity, room_id, True)
    return call(desk.sync_requests, store.conn, identity.tenant_id, room_id, run, identity.user_id)


def write_request(room_id, body, record_id, store, identity):
    _, run = context(store, identity, room_id, True)
    data = body.model_dump(exclude={'expected_version'})
    if data['accepted_evidence']:
        call(desk.validate_links, data['accepted_evidence'], desk.evidence(store.conn, identity.tenant_id, room_id, run))
    if record_id:
        old = next((r for r in desk.records(store.conn, identity.tenant_id, room_id, 'request') if r['id'] == record_id), None)
        if old is None:
            raise HTTPException(404, 'Request not found')
        data = {**old, **data}
    return call(desk.put_request, store.conn, identity.tenant_id, room_id, identity.user_id, data, record_id, body.expected_version)


@router.post('/requests')
def create_request(room_id: str, body: Request, store=Depends(get_store), identity=Depends(get_identity)):
    return write_request(room_id, body, None, store, identity)


@router.post('/requests/{request_id}')
def update_request(room_id: str, request_id: str, body: Request, store=Depends(get_store), identity=Depends(get_identity)):
    return write_request(room_id, body, request_id, store, identity)


class Grant(Link):
    scope: str = Field(default='', max_length=200)
    enabled: bool = True


@router.post('/grants')
def grant(room_id: str, body: Grant, store=Depends(get_store), identity=Depends(get_identity)):
    _, run = context(store, identity, room_id, True)
    return call(desk.grant, store.conn, identity.tenant_id, room_id, run, identity.user_id, **body.model_dump())


class Part(Strict):
    question: str = Field(min_length=1, max_length=2000)
    required_record: str = Field(min_length=1, max_length=2000)


class Question(Strict):
    scope: str = Field(default='', max_length=200)
    parts: list[Part] = Field(min_length=1, max_length=20)


@router.post('/answers')
def draft(room_id: str, body: Question, store=Depends(get_store), identity=Depends(get_identity)):
    _, run = context(store, identity, room_id, True)
    if run is None:
        raise HTTPException(409, 'Create a fact-base run before using the Q&A desk')
    # Each answer has a private call directory; simultaneous calls cannot overwrite their recordings.
    import secrets
    from pathlib import Path
    from delivery.deal_documents.llm import RecordedModel
    model = RecordedModel(Path(run['run_dir']) / 'diligence' / secrets.token_hex(12), run['model'])
    return call(desk.draft_answer, store.conn, identity.tenant_id, room_id, run, identity.user_id,
                body.scope, [p.model_dump() for p in body.parts], model)


class Approval(Strict):
    expected_version: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=4000)
    acknowledge_conflicts: bool = False


@router.post('/answers/{answer_id}/approve')
def approve(room_id: str, answer_id: str, body: Approval, store=Depends(get_store), identity=Depends(get_identity)):
    _, run = context(store, identity, room_id, True)
    return call(desk.approve_answer, store.conn, identity.tenant_id, room_id, run, identity.user_id,
                answer_id, body.expected_version, body.note, body.acknowledge_conflicts)


class Artifact(Strict):
    phase: Literal['facts', 'memo', 'decks']
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Event(Strict):
    counterparty: str = Field(min_length=1, max_length=200)
    stage: Literal['contact_recorded', 'nda_executed', 'materials_reviewed', 'meeting', 'indicative_offer', 'binding_commitment', 'closed']
    state: Literal['planned', 'occurred', 'cancelled']
    date: str
    owner: str = Field(min_length=1, max_length=200)
    next_action: str = Field(default='', max_length=2000)
    next_date: str | None = None
    evidence: list[Link] = Field(default_factory=list, max_length=100)
    artifact: Artifact | None = None
    review_note: str = Field(default='', max_length=4000)
    expected_version: int = Field(default=0, ge=0)


@router.post('/events')
def create_event(room_id: str, body: Event, store=Depends(get_store), identity=Depends(get_identity)):
    _, run = context(store, identity, room_id, True)
    return call(desk.put_event, store.conn, identity.tenant_id, room_id, run, identity.user_id,
                body.model_dump(exclude={'expected_version'}), expected=body.expected_version)


@router.post('/events/{event_id}')
def update_event(room_id: str, event_id: str, body: Event, store=Depends(get_store), identity=Depends(get_identity)):
    _, run = context(store, identity, room_id, True)
    if not any(e['id'] == event_id for e in desk.records(store.conn, identity.tenant_id, room_id, 'event')):
        raise HTTPException(404, 'Event not found')
    return call(desk.put_event, store.conn, identity.tenant_id, room_id, run, identity.user_id,
                body.model_dump(exclude={'expected_version'}), event_id, body.expected_version)
