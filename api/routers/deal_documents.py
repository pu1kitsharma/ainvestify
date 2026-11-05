"""Room API for the phased deal-documents workflow: status with timings, phase control, approvals and draft files.

Phases run in the local worker (scripts/deal_documents_worker.py). The API only
records requests and decisions; every state shown comes from the database, so
it survives refreshes and restarts. Drafts stay private to the sandbox; nothing
here releases or sends a document to an investor.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from api.deps import get_identity, get_store
from api.routers.rooms import require_room
from delivery.deal_documents import runs

router = APIRouter(prefix='/api/rooms', tags=['deal-documents'])
ROOT = Path(os.environ.get('DEAL_DOCUMENTS_ROOT', '/home/investify/private/deal_documents'))
MODEL = os.environ.get('DEAL_DOCUMENTS_MODEL', 'qwen3.6:35b-a3b')
FILES = {
    'financial_baseline.json': ('memo', 'Canonical financial baseline and source choices', 'application/json'),
    'source_ledger.json': ('memo', 'Every-number source ledger (JSON)', 'application/json'),
    'source_ledger.md': ('memo', 'Every-number source ledger (review copy)', 'text/markdown'),
    'deck_source_ledger.json': ('decks', 'Cross-document source ledger (JSON)', 'application/json'),
    'deck_source_ledger.md': ('decks', 'Cross-document source ledger (review copy)', 'text/markdown'),
    'facts.md': ('facts', 'Fact base with sources and reconciliation findings', 'text/markdown'),
    'memo.md': ('memo', 'Memorandum review copy (citations, calculations, reviewer issues)', 'text/markdown'),
    'compliance.md': ('memo', 'Compliance gate and questions for counsel', 'text/markdown'),
    'open_items.md': ('memo', 'Open items for the company to answer before release', 'text/markdown'),
    'investment_memorandum.pptx': ('memo', 'Investment memorandum (PowerPoint)', 'application/octet-stream'),
    'investment_memorandum.pdf': ('memo', 'Investment memorandum (PDF)', 'application/pdf'),
    'investment_memorandum.preview.pdf': ('memo', 'Live memorandum preview (in progress, not reviewed)', 'application/pdf'),
    'decks.md': ('decks', 'Deck review copy (slides, citations, reviewer issues)', 'text/markdown'),
    'deck_compliance.md': ('decks', 'Deck compliance gate and questions for counsel', 'text/markdown'),
    'pitch_deck.pptx': ('decks', 'Pitch deck (PowerPoint)', 'application/octet-stream'),
    'pitch_deck.pdf': ('decks', 'Pitch deck (PDF)', 'application/pdf'),
    'intro_deck.pptx': ('decks', 'Introductory deck (PowerPoint)', 'application/octet-stream'),
    'intro_deck.pdf': ('decks', 'Introductory deck (PDF)', 'application/pdf'),
}

# What a reader wants to know about the company, and the memorandum sections that answer it.
TOPICS = (('The investment case', ('Investment summary',)),
          ('The business', ('Company overview', 'Products and business model', 'Distribution and partnerships', 'Management team')),
          ('Market and competition', ('Market opportunity', 'Competitive landscape')),
          ('Financial results and capital', ('Historical financial performance', 'Capitalisation and funding history')),
          ('Company projections', ('Projections and key assumptions',)),
          ('Risks and regulation', ('Key risks', 'Regulatory considerations')))
VERSION = re.compile(r'^\d{8}T\d{6}Z$')
PROGRESS_HEADING = re.compile(r'^## (.+) \((?:first draft|revised after review); .+\)$')


def progress_sections(text):
    """The sections written so far, from the in-progress memo file, without its working notes."""
    sections = []
    for line in text.splitlines():
        heading = PROGRESS_HEADING.match(line)
        if heading:
            sections.append({'title': heading.group(1), 'paragraphs': []})
        elif sections and line.strip() and not line.startswith('- open problem:'):
            sections[-1]['paragraphs'].append(line.strip())
    return sections


def draft_sections(run_dir):
    final, progress = run_dir / 'memo.json', run_dir / 'memo.md'
    if final.exists():
        return [{'title': section['title'], 'paragraphs': ([section['headline']] if section.get('headline') else []) +
                 [p['text'] for p in section['paragraphs'] if p['kind'] != 'question']} for section in json.loads(final.read_text())]
    if progress.exists() and progress.read_text().startswith('# Investment memorandum — IN PROGRESS'):
        return progress_sections(progress.read_text())
    preview = run_dir / 'pages.preview.json'
    if preview.exists():
        return [{'title': page['title'] or page['brief'], 'paragraphs': page['takeaways']}
                for page in json.loads(preview.read_text())['pages'] if page.get('page_status') != 'pending']
    return []


def earlier_versions(run_dir):
    """Every finished earlier generation, newest first, so a rerun never leaves the room empty. A folder with no document in it was an interrupted rerun."""
    versions = []
    folders = (run_dir / 'superseded').iterdir() if (run_dir / 'superseded').is_dir() else ()
    for folder in sorted((path for path in folders if VERSION.match(path.name)), key=lambda path: path.name, reverse=True):
        present = [(name, folder / name) for name in FILES if (folder / name).exists()]
        if not any(name.endswith('.pdf') and '.preview.' not in name for name, _ in present):
            continue
        review = folder / 'memo_review.json'
        rounds = json.loads(review.read_text()).get('climb', []) if review.exists() else []
        versions.append({'version': folder.name, 'updated': max(path.stat().st_mtime for _, path in present), 'rounds': rounds,
                         'files': [{'name': name, 'phase': FILES[name][0], 'label': FILES[name][1]} for name, _ in present]})
    return versions


def _run(store, identity, room_id):
    require_room(store, identity, room_id)
    return runs.get(store.conn, identity.tenant_id, room_id)


def _owner(identity):
    if identity.role != 'owner':
        raise HTTPException(403, 'Only the sandbox owner can control document generation and approve phases')


def _qualified_compliance(store, identity):
    from delivery.compliance import qualified_compliance_owners
    owner = qualified_compliance_owners(store.conn, identity.tenant_id).get(identity.user_id)
    today = datetime.date.today()
    if owner and owner.valid_from <= today <= owner.valid_until and 'IN' in owner.jurisdictions:
        return owner
    return None


@router.get('/from-lead/{lead_id}/deal-documents')
def room_for_lead(lead_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    """The company's room when it has a document run. Read-only: viewing a company must not activate a room or queue a job."""
    workspace = store.get_workspace(identity.tenant_id, lead_id=lead_id)
    try:
        run = _run(store, identity, workspace.id) if workspace else None
    except HTTPException:
        run = None
    return {'room_id': workspace.id if run else None}


@router.get('/{room_id}/deal-documents/overview')
def overview(room_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    """The current draft arranged by what a reader wants to know, available from the first written section."""
    run = _run(store, identity, room_id)
    if run is None:
        raise HTTPException(404, 'No document run in this room')
    sections = {section['title']: section for section in draft_sections(Path(run['run_dir']))}
    grouped = [{'title': title, 'sections': [sections[name] for name in names if name in sections]} for title, names in TOPICS]
    known = {name for _, names in TOPICS for name in names}
    other = [section for name, section in sections.items() if name not in known]
    return {'topics': grouped + ([{'title': 'Memorandum pages', 'sections': other}] if other else [])}


@router.get('/{room_id}/deal-documents')
def status(room_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    run = _run(store, identity, room_id)
    files = []
    if run:
        for name, (phase, label, _) in FILES.items():
            path = Path(run['run_dir']) / name
            if path.exists():
                files.append({'name': name, 'phase': phase, 'label': label, 'size': path.stat().st_size,
                              'updated': path.stat().st_mtime})
    return {'run': runs.public(run), 'files': files, 'earlier': earlier_versions(Path(run['run_dir'])) if run else [], 'is_owner': identity.role == 'owner',
            'qualified_compliance_reviewer': _qualified_compliance(store, identity) is not None}


class StartOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    generation_path: Literal['page_first', 'prose'] | None = None


class BaselineMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric: str = Field(min_length=1, max_length=200)
    period: str = Field(max_length=100)
    unit: str = Field(min_length=1, max_length=100)
    basis: Literal['historical', 'projection', 'target', 'company_claim', 'third_party', 'definition', 'company_model']
    segment: str = Field(default='', max_length=200)
    definition: str = Field(default='', max_length=500)
    case: str = Field(default='', max_length=100)
    version: str = Field(default='', max_length=100)
    perimeter: str = Field(default='', max_length=200)
    financial_role: Literal['', 'asset_total', 'liability_total', 'equity_total', 'opening_cash', 'net_cash_change',
                            'closing_cash', 'gross_revenue', 'revenue_deduction', 'net_revenue',
                            'contribution_base', 'contribution_cost', 'contribution'] = ''
    cost_boundary: str = Field(default='', max_length=200)


class BaselineChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    row_id: str = Field(min_length=64, max_length=64)
    source_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=10, max_length=1000)
    mapping: BaselineMapping | None = None


@router.get('/{room_id}/deal-documents/ledger')
def source_ledger(room_id: str, decks: bool = False, store=Depends(get_store), identity=Depends(get_identity)):
    run = _run(store, identity, room_id)
    if not run:
        raise HTTPException(404, 'No document run in this room')
    path = Path(run['run_dir']) / ('deck_source_ledger.json' if decks else 'source_ledger.json')
    return json.loads(path.read_text()) if path.exists() else None


@router.post('/{room_id}/deal-documents/baseline-choice', status_code=202)
def baseline_choice(room_id: str, body: BaselineChoice, store=Depends(get_store), identity=Depends(get_identity)):
    """A source choice always regenerates the memo and invalidates dependent approvals."""
    from delivery.deal_documents import ledger
    from delivery.deal_documents.pipeline import _fact_base
    _owner(identity)
    run = _run(store, identity, room_id)
    if not run:
        raise HTTPException(404, 'No document run in this room')
    if len(body.reason.strip()) < 10:
        raise HTTPException(422, 'Record a reason of at least ten non-padding characters')
    if any(phase['state'] in ('queued', 'running') for phase in run['data']['phases'].values()):
        raise HTTPException(409, 'Wait for the current phase to finish before changing the baseline')
    reason = runs.phase_ready(run, 'memo')
    if reason:
        raise HTTPException(409, reason)
    facts, _ = _fact_base(run)
    review = facts.setdefault('ledger_review', {})
    review.setdefault('mappings', {})
    row = next((row for row in ledger.baseline(facts)['rows'] if row['id'] == body.row_id), None)
    candidate = next((candidate for candidate in row['candidates'] if candidate['id'] == body.source_id), None) if row else None
    if candidate is None:
        raise HTTPException(409, 'Choose a source belonging to this baseline row')
    if body.mapping:
        review['mappings'][body.source_id] = body.mapping.model_dump()
        row = next(row for row in ledger.baseline(facts)['rows'] if any(c['id'] == body.source_id for c in row['candidates']))
        candidate = next(c for c in row['candidates'] if c['id'] == body.source_id)
    if candidate['unsafe']:
        raise HTTPException(409, 'Choose a verified source belonging to this baseline row')
    def change(data):
        if any(phase['state'] in ('queued', 'running') for phase in data['phases'].values()):
            raise ValueError('Another phase is in progress')
        if body.mapping:
            data.setdefault('baseline_mappings', {})[body.source_id] = body.mapping.model_dump()
        data.setdefault('baseline_choices', {})[row['id']] = {'source_id': body.source_id, 'reason': body.reason.strip(), 'by': identity.user_id,
                                                            'observation_sha256': candidate['observation_sha256']}
        current = data['phases']['memo']
        data['phases']['memo'] = {**runs.empty_phase(), 'state': 'queued', 'queued_at': time.time(), 'queued_by': identity.user_id,
                                  'history': current.get('history', [])[-5:]}
        data['phases']['decks']['approvals'] = {}
        data['phases']['decks']['stale'] = True
        data.setdefault('events', []).append({'at': time.time(), 'text': f'Baseline source choice recorded by {identity.user_id}; memorandum queued'})
        data['events'] = data['events'][-60:]
    try:
        runs.update(store.conn, run['id'], change)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return runs.public(runs.get_by_id(store.conn, run['id']))


@router.post('/{room_id}/deal-documents/{phase}/start', status_code=202)
def start(room_id: str, phase: Literal['facts', 'memo', 'decks'], body: StartOptions | None = None,
          store=Depends(get_store), identity=Depends(get_identity)):
    _owner(identity)
    room = require_room(store, identity, room_id)
    if not room.deal_id:
        raise HTTPException(409, 'Upload the company documents to this room first')
    run = runs.get(store.conn, identity.tenant_id, room_id)
    if run is None:
        lead = store.get_lead(identity.tenant_id, room.lead_id)
        run_dir = ROOT / identity.tenant_id / room_id
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        run = runs.create(store.conn, identity.tenant_id, room_id, room.deal_id, lead.company_name if lead else room_id, run_dir, MODEL)
    try:
        runs.queue(store.conn, run, phase, identity.user_id, generation_path=body.generation_path if body else None)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return runs.public(runs.get(store.conn, identity.tenant_id, room_id))


@router.post('/{room_id}/deal-documents/{phase}/cancel')
def cancel(room_id: str, phase: Literal['facts', 'memo', 'decks'], store=Depends(get_store), identity=Depends(get_identity)):
    _owner(identity)
    run = _run(store, identity, room_id)
    if run is None:
        raise HTTPException(404, 'No document run in this room')
    try:
        runs.request_cancel(store.conn, run, phase, identity.user_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return runs.public(runs.get(store.conn, identity.tenant_id, room_id))


class Approval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notes: str = Field(default='', max_length=8000)


@router.post('/{room_id}/deal-documents/{phase}/approve')
def approve(room_id: str, phase: Literal['facts', 'memo', 'decks'], body: Approval, store=Depends(get_store),
            identity=Depends(get_identity)):
    _owner(identity)
    run = _run(store, identity, room_id)
    if run is None:
        raise HTTPException(404, 'No document run in this room')
    try:
        runs.approve(store.conn, run, phase, 'operator', {'by': identity.user_id, 'notes': body.notes, 'decision': 'approved'})
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return runs.public(runs.get(store.conn, identity.tenant_id, room_id))


class Waiver(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=10, max_length=1000)


class ComplianceSignoff(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['approved', 'changes_required']
    notes: str = Field(min_length=10, max_length=8000)
    waivers: list[Waiver] = Field(default_factory=list, max_length=40)


@router.post('/{room_id}/deal-documents/memo/compliance-signoff')
def compliance_signoff(room_id: str, body: ComplianceSignoff, store=Depends(get_store), identity=Depends(get_identity)):
    """Recorded by an operator-provisioned qualified compliance reviewer; never by the model or the owner role alone."""
    owner = _qualified_compliance(store, identity)
    if owner is None:
        raise HTTPException(403, 'Compliance sign-off needs an active qualified compliance reviewer account for India')
    run = _run(store, identity, room_id)
    if run is None:
        raise HTTPException(404, 'No document run in this room')
    gate = json.loads((Path(run['run_dir']) / 'compliance.json').read_text())
    waived = {waiver.key for waiver in body.waivers}
    if body.decision == 'approved' and set(gate['blockers']) - waived:
        raise HTTPException(409, 'Resolve or waive every failing compliance check first: ' + ', '.join(sorted(set(gate['blockers']) - waived)))
    try:
        runs.approve(store.conn, run, 'memo', 'compliance', {
            'by': identity.user_id, 'authority_record_id': owner.authority_record_id, 'decision': body.decision,
            'notes': body.notes, 'waivers': [waiver.model_dump() for waiver in body.waivers]})
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return runs.public(runs.get(store.conn, identity.tenant_id, room_id))


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(default='', max_length=4000)


@router.post('/{room_id}/deal-documents/questions/{question_id}/answer')
def answer(room_id: str, question_id: str, body: Answer, store=Depends(get_store), identity=Depends(get_identity)):
    """Record the company's answer. It is stored as the company's statement and cited as such, not as a verified fact."""
    _owner(identity)
    run = _run(store, identity, room_id)
    if run is None:
        raise HTTPException(404, 'No document run in this room')
    try:
        runs.answer_question(store.conn, run, question_id, body.text.strip(), identity.user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return runs.public(runs.get(store.conn, identity.tenant_id, room_id))


@router.get('/{room_id}/deal-documents/memo')
def memo(room_id: str, store=Depends(get_store), identity=Depends(get_identity)):
    """The memorandum as sections with validation problems, reviewer issues and the compliance gate, for in-app review."""
    run = _run(store, identity, room_id)
    if run is None:
        raise HTTPException(404, 'No document run in this room')
    run_dir = Path(run['run_dir'])
    def load(name, default=None):
        path = run_dir / name
        return json.loads(path.read_text()) if path.exists() else default
    sections = load('memo.json', [])
    return {'sections': [{key: section.get(key) for key in ('section', 'title', 'state', 'problems', 'revised_from_review')}
                         | {'removed_sentences': section.get('removed_sentences', [])}
                         | {'paragraphs': [{'kind': p['kind'], 'text': p['text'], 'cites': p['cites']} for p in section['paragraphs']],
                            'calculations': [{'id': k, **{f: v[f] for f in ('label', 'text', 'kind')}}
                                             for k, v in section.get('results', {}).items() if isinstance(v, dict)]}
                         for section in sections],
            'review': load('memo_review.json'), 'compliance': load('compliance.json'),
            'pages': load('pages.preview.json', {}).get('pages', [])}


@router.get('/{room_id}/deal-documents/files/{name}')
def file(room_id: str, name: str, version: str | None = None, store=Depends(get_store), identity=Depends(get_identity)):
    if name not in FILES or (version is not None and not VERSION.match(version)):
        raise HTTPException(404, 'File not found')
    run = _run(store, identity, room_id)
    folder = Path(run['run_dir']) / 'superseded' / version if run and version else Path(run['run_dir']) if run else None
    path = folder / name if folder else None
    if path is None or not path.exists():
        raise HTTPException(404, 'File not generated yet')
    _, _, media = FILES[name]
    inline = media in ('application/pdf', 'text/markdown')
    return Response(path.read_bytes(), media_type='text/plain; charset=utf-8' if media == 'text/markdown' else media, headers={
        'Content-Disposition': f'{"inline" if inline else "attachment"}; filename="DRAFT-{name}"',
        'X-Content-Type-Options': 'nosniff', 'X-Artifact-State': 'draft', 'Cache-Control': 'no-store'})
