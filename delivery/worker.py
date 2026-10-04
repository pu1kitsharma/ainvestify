"""Bounded deterministic room stages with durable checkpoints and scoped subprocesses."""
from __future__ import annotations
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import time

from delivery import jobs
from delivery.inspection import summarize_report
from delivery.isolation import run_private
from delivery.artifacts import register_draft
from security.identity import has_access
from store import Store

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/private_document_worker.py'
PREVIEW_FILES = (
    ('intro.pptx', 'intro_deck_preview', 'pptx'),
    ('intro.pdf', 'intro_deck_preview', 'pdf'),
    ('pitch.pptx', 'pitch_deck_preview', 'pptx'),
    ('pitch.pdf', 'pitch_deck_preview', 'pdf'),
    ('memo.docx', 'investment_memorandum_preview', 'docx'),
    ('memo.pdf', 'investment_memorandum_preview', 'pdf'),
)


def frozen_material_preview(job, memo, material, title, *, timeout):
    """Render once, freeze bytes before any artifact registration, then replay.

    A lease may expire between registering the six artifacts. Retrying then
    reads this exact private bundle, so occupied artifact slots cannot receive
    different Office/PDF bytes from a second renderer invocation.
    """
    from agents.inference.model_authorship import digest
    from delivery.investment_memo_stage import memo_directory
    from delivery.material_stage import validate_material_checkpoint
    accepted = validate_material_checkpoint(job, memo, material)
    request = {'operation': 'render', 'title': title,
               'memo_sections': memo['sections'],
               'intro_sections': accepted['decks']['intro_deck']['sections'],
               'pitch_sections': accepted['decks']['pitch_deck']['sections']}
    scope = {'contract': 'material_preview_v1', 'tenant_id': job['tenant_id'],
             'workspace_id': job['workspace_id'], 'input_revision': job['input_revision'],
             'source_hash': memo['source_hash'], 'material_digest': digest(accepted),
             'render_request_digest': digest(request)}
    parent = memo_directory(job)
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    frozen = parent / 'material_preview'
    if not frozen.exists():
        with tempfile.TemporaryDirectory(prefix='.material-preview-', dir=parent) as directory:
            candidate = Path(directory)
            (candidate / 'request.json').write_text(json.dumps(request, ensure_ascii=False))
            font_root = Path('/Applications/LibreOffice.app/Contents/Resources/fonts/truetype')
            run_private([sys.executable, SCRIPT], candidate, timeout=timeout,
                extra_read=(font_root,) if font_root.is_dir() else ())
            files = {name: hashlib.sha256((candidate / name).read_bytes()).hexdigest()
                     for name, _, _ in PREVIEW_FILES}
            (candidate / 'manifest.json').write_text(json.dumps({**scope, 'files': files},
                                                             ensure_ascii=False))
            candidate.rename(frozen)
    manifest = json.loads((frozen / 'manifest.json').read_text())
    if ({key: manifest.get(key) for key in scope} != scope or
            set(manifest.get('files', {})) != {name for name, _, _ in PREVIEW_FILES} or
            any(hashlib.sha256((frozen / name).read_bytes()).hexdigest() != manifest['files'][name]
                for name, _, _ in PREVIEW_FILES)):
        raise ValueError('Frozen material preview differs from accepted material or bytes')
    return frozen, scope


def public_kb_checkpoint(profile):
    provenance = profile.provenance
    if provenance.get('origin') != 'public_kb':
        return {'public_kb': 'no_bound_source', 'source_rights': 'not_applicable'}
    from public_kb.ingestion import PublicIngestion
    root = Path(__file__).resolve().parents[1]/'runtime_public_kb'
    if not (root/'kb.db').is_file():
        raise ValueError('Bound public KB registry unavailable')
    kb = PublicIngestion(root/'kb.db',root/'archive')
    try:
        source_id, version = provenance.get('source_id'), provenance.get('source_version')
        kb.approved_source(source_id)
        row = kb.conn.execute("""SELECT v.state FROM versions v JOIN fetch_state f
            ON f.source_id=v.source_id AND f.last_sha256=v.sha256
            WHERE v.source_id=? AND v.sha256=?""",(source_id,version)).fetchone()
        if not row or row[0] != 'indexed':
            raise ValueError('Bound public KB source is stale or unindexed')
        return {'public_kb': 'indexed_source_bound', 'source_rights': 'reviewed_registry',
                'source_id': source_id, 'source_version': version}
    finally:
        kb.close()


def financial_checkpoint(inventories):
    if not inventories:
        return {"state": "awaiting_input", "reason": "company_model_or_reviewed_assumptions_required"}
    codes = {finding.get("code") for report in inventories.values()
             for finding in report.get("findings", [])}
    errors = {"stored_cell_error", "broken_formula_reference", "broken_defined_name",
              "missing_formula_cache", "circular_formula_reference"}
    if codes & errors:
        return {"state": "blocked", "reason": "source_workbook_formula_errors",
                "error_count": sum(finding.get("code") in errors
                    for report in inventories.values()
                    for finding in report.get("findings", []))}
    return {"state": "blocked", "reason": "formula_dependency_and_recalculation_review_required"}


def memo_source_groups(coverage):
    """Count publisher channels, not pages or files, for memo qualification."""
    return coverage['public_publishers'] + min(coverage['private_documents'], 1)


def memo_coverage_issue(coverage):
    """Every retained passage must be included or explicitly model-adjudicated."""
    if coverage.get('coverage_complete') is not True or coverage.get('omitted_passages') != 0:
        return 'source_coverage_incomplete'
    return None


def draft_memo_issue(coverage, recommendation):
    """A single-channel memo can only communicate a model-authored deferral."""
    if issue := memo_coverage_issue(coverage):
        return issue
    if memo_source_groups(coverage) == 0:
        return 'no_usable_source_group'
    if memo_source_groups(coverage) == 1 and recommendation != 'defer_pending_evidence':
        return 'single_source_requires_model_defer'
    return None


def process_one(db_path):
    from api.routers.rooms import revision_for
    with Store(db_path) as store:
        job=jobs.claim(store.conn)
        if job is None:return None
        started=time.monotonic()
        data=dict(job['checkpoint'])
        phase = job.get('phase', 'legacy')
        phase_limit = jobs._phase_cap(job)
        def can_retry():
            limit = phase_limit
            if phase == 'draft':
                from delivery.investment_memo_stage import memo_directory
                profile_path = memo_directory(job) / 'model.json'
                if profile_path.is_file():
                    contract = json.loads(profile_path.read_text()).get('memo_draft_contract')
                    limit = jobs._phase_cap({**job, 'checkpoint': {
                        **data, 'memo_draft_contract': contract}})
            elif phase == 'review' and data.get('memo_revision') != job.get(
                    'checkpoint', {}).get('memo_revision'):
                limit = jobs._phase_cap({**job, 'checkpoint': data})
            return (job.get('phase_attempt', job['attempt']) < limit
                    and (phase != 'legacy' or job['attempt'] < 3))
        def save(state='running',error=None, next_phase=None):
            if time.monotonic()-started>120:raise TimeoutError('room_pass_budget_exhausted')
            if next_phase == 'draft' or phase == 'draft':
                # The draft cap is tied to the memo contract frozen for this job.
                # An older saved profile must keep its original six-pass limit.
                from delivery.investment_memo_stage import memo_directory
                memo_root = memo_directory(job)
                profile_path = memo_root / 'model.json'
                if profile_path.is_file():
                    profile = json.loads(profile_path.read_text())
                    contract = profile.get('memo_draft_contract')
                    if contract not in {None, 'memo-cards-v1', 'memo-cards-v2',
                                        'memo-cards-v3', 'memo-cards-v4',
                                        'memo-cards-v5', 'memo-cards-v6',
                                        'memo-cards-v7', 'memo-cards-v8',
                                        'memo-cards-v9', 'memo-cards-v10',
                                        'memo-cards-v11', 'memo-cards-v12',
                                        'memo-cards-v13'}:
                        raise ValueError('Unknown frozen memo draft contract')
                    causal_contract = profile.get('memo_causal_review_contract')
                    final_contract = profile.get('memo_final_review_contract')
                    if final_contract not in {None, 'field_v1', 'field_v2', 'field_v3', 'field_v4'} or (
                            final_contract and contract != 'memo-cards-v13'):
                        raise ValueError('Unknown frozen final memo review contract')
                    if causal_contract not in {None, 'memo-causal-v1',
                                               'memo-causal-v2', 'memo-causal-v3'} or (
                            causal_contract and contract not in {
                                'memo-cards-v3', 'memo-cards-v4',
                                'memo-cards-v5', 'memo-cards-v6',
                                'memo-cards-v7', 'memo-cards-v8',
                                'memo-cards-v9', 'memo-cards-v10',
                                'memo-cards-v11', 'memo-cards-v12',
                                'memo-cards-v13'}):
                        raise ValueError('Unknown frozen memo causal review contract')
                    if contract is None:
                        data.pop('memo_draft_contract', None)
                    else:
                        data['memo_draft_contract'] = contract
                    if causal_contract is None:
                        data.pop('memo_causal_review_contract', None)
                    else:
                        data['memo_causal_review_contract'] = causal_contract
                    if final_contract is None:
                        data.pop('memo_final_review_contract', None)
                    else:
                        data['memo_final_review_contract'] = final_contract
                elif (memo_root / 'attempts.json').exists():
                    raise ValueError('Saved memo attempts lack a frozen model profile')
                else:
                    data['memo_draft_contract'] = 'memo-cards-v2'
                    data.pop('memo_causal_review_contract', None)
                    data.pop('memo_final_review_contract', None)
            jobs.checkpoint(store.conn,job,data,state=state,error=error,phase=next_phase)
        try:
            if not has_access(store.conn,job['actor_id'],job['tenant_id']):
                raise PermissionError('revoked')
            room=store.get_workspace(job['tenant_id'],workspace_id=job['workspace_id'])
            current_revision = revision_for(store,room) if room is not None else None
            if current_revision!=job['input_revision']:
                data['revision_check']={'room_found':room is not None,
                    'expected':job['input_revision'],'actual':current_revision}
                save('blocked','input_revision_changed');return job['id']
            lead=store.get_lead(job['tenant_id'],room.lead_id)
            data['evidence']={'state':'recorded','recorded_claim_count':len(lead.company_profile.evidence),
                'identity_state':lead.company_profile.identity_status,
                **public_kb_checkpoint(lead.company_profile)}
            save()
            documents=store.get_documents_for_deal(job['tenant_id'],room.deal_id) if room.deal_id else []
            data['evidence']['documents_outside_workbook_inventory'] = sum(document.type != 'xlsx' for document in documents)
            inventories=data.setdefault('workbooks',{})
            workbook_count = sum(document.type == 'xlsx' for document in documents)
            # Financial selection is finite. Do not parse an arbitrary upload
            # set before the financial phase can record that review is needed.
            inventory_documents = documents if phase == 'legacy' or workbook_count <= 3 else []
            for document in inventory_documents:
                if document.type!='xlsx' or document.id in inventories:continue
                if not has_access(store.conn,job['actor_id'],job['tenant_id']):raise PermissionError('revoked')
                # Only the document already resolved through tenant/deal storage
                # is copied into this parser's isolated filesystem view.
                from delivery.storage import read_source_bytes
                with tempfile.TemporaryDirectory(prefix='private-room-') as directory:
                    root=Path(directory)
                    (root/'input.bin').write_bytes(read_source_bytes(document.storage_uri))
                    (root/'request.json').write_text(json.dumps({'operation':'inspect','format':'xlsx'}))
                    run_private([sys.executable,SCRIPT],root,timeout=max(1,120-(time.monotonic()-started)))
                    inventories[document.id]=summarize_report(json.loads((root/'result.json').read_text()))
                save()
            data.setdefault('financial_model',financial_checkpoint(inventories))
            save()
            if phase == 'financial_analysis':
                from agents.inference.local_models import PreparationModel, shared_model_name
                from delivery.financial_stage import run_financial_stage
                workbook_documents = sorted((document for document in documents
                    if document.type == 'xlsx'), key=lambda document: document.id)
                financial = data.setdefault('financial_analysis', {'documents': {}})
                recorded = financial.setdefault('documents', {})
                if len(workbook_documents) > 3:
                    financial.update({'state': 'blocked',
                        'reason': 'more_than_three_workbooks_need_reviewed_selection',
                        'workbook_count': len(workbook_documents)})
                    data['financial_model'] = {'state': 'blocked',
                        'reason': 'financial_reconciliation_and_review_required'}
                    save('queued', next_phase='draft')
                    return job['id']
                pending = next((document for document in workbook_documents
                    if recorded.get(document.id, {}).get('state') not in
                    {'partial_evidence', 'blocked'}), None)
                if pending is not None:
                    remaining = 120 - (time.monotonic() - started)
                    if remaining < 25:
                        if can_retry():
                            save('queued')
                        else:
                            recorded[pending.id] = {'state': 'blocked',
                                'reason': 'bounded_financial_phase_exhausted'}
                            financial['state'] = 'blocked'
                            data['financial_model'] = {'state': 'blocked',
                                'reason': 'financial_reconciliation_and_review_required'}
                            save('queued', next_phase='draft')
                        return job['id']
                    as_of_date = datetime.fromtimestamp(job['created'],timezone.utc).date().isoformat()
                    recorded[pending.id] = run_financial_stage(
                        store, job, pending, model_name=shared_model_name(PreparationModel()),
                        as_of_date=as_of_date, timeout=min(110,remaining-5),
                        budget_seconds=105)
                    save()
                    if recorded[pending.id]['state'] == 'needs_resume':
                        if can_retry():
                            save('queued')
                            return job['id']
                        recorded[pending.id] = {'state': 'blocked',
                            'reason': 'bounded_financial_phase_exhausted'}
                    elif any(document.id not in recorded for document in workbook_documents):
                        if can_retry():
                            save('queued')
                            return job['id']
                        financial['state'] = 'blocked'
                        financial['reason'] = 'bounded_financial_phase_exhausted'
                states = [recorded.get(document.id, {}).get('state')
                    for document in workbook_documents]
                if not workbook_documents:
                    financial['state'] = 'awaiting_input'
                    data['financial_model'] = financial_checkpoint(inventories)
                elif states and all(state == 'partial_evidence' for state in states):
                    financial['state'] = 'partial_evidence'
                    data['financial_model'] = {'state': 'partial_evidence',
                        'reason': 'financial_reconciliation_and_review_required',
                        'document_count': len(states)}
                else:
                    financial['state'] = 'blocked'
                    financial.setdefault('reason', 'financial_reconciliation_and_review_required')
                    data['financial_model'] = {'state': 'blocked',
                        'reason': 'financial_reconciliation_and_review_required',
                        'document_states': states}
                save('queued', next_phase='draft')
                return job['id']
            from delivery.investment_memo_stage import (room_sources, resolve_memo_sources,
                                                         run_memo_pass, source_fingerprint)
            inventory, coverage = room_sources(store, lead, room, full_inventory=True)
            remaining = 120 - (time.monotonic() - started)
            if coverage.get('coverage_complete') is not True or coverage.get('source_count') > 30 or sum(
                    len(source.passage) for source in inventory) > 24000:
                if remaining < 20:
                    data['investment_memo'] = {'state': 'needs_resume',
                        'reason': 'room_pass_time_limit', 'coverage': coverage}
                    save('queued' if can_retry() else 'awaiting_input')
                    return job['id']
                selection = resolve_memo_sources(job, lead, inventory, coverage,
                    timeout=min(110, remaining - 5))
                if selection['state'] != 'complete':
                    data['investment_memo'] = {'state': selection['state'],
                        'reason': selection['reason'],
                        'coverage': selection.get('coverage', coverage)}
                    data['materials'] = {'state': 'awaiting_input',
                        'reason': selection['reason']}
                    save('queued' if selection['state'] == 'needs_resume' and can_retry()
                         else 'awaiting_input')
                    return job['id']
                sources, coverage = selection['sources'], selection['coverage']
            else:
                sources = inventory
            # Multiple uploads from one room are one counterparty channel;
            # their file count is not independent corroboration.
            source_groups = memo_source_groups(coverage)
            inventory_digest = (coverage.get('inventory_digest')
                                if coverage.get('selection_applied') else None)
            current_hash = source_fingerprint(job, lead, sources, inventory_digest)
            memo = data.get('investment_memo', {})
            recorded_hash = data.get('memo_source_hash') or memo.get('source_hash')
            if recorded_hash and recorded_hash != current_hash:
                data['investment_memo'] = {'state': 'blocked', 'reason': 'source_version_changed',
                                           'coverage': coverage}
                save('blocked', 'source_version_changed')
                return job['id']
            if phase in {'correction', 'ledger', 'review'} and not recorded_hash:
                raise ValueError('Memo phase lacks a saved source fingerprint')
            if issue := memo_coverage_issue(coverage):
                data['investment_memo'] = {'state': 'awaiting_input', 'reason': issue,
                                           'coverage': coverage}
                data['materials'] = {'state': 'awaiting_input', 'reason': issue}
                save('awaiting_input')
                return job['id']
            if source_groups < 1:
                data['investment_memo'] = {'state': 'awaiting_input',
                    'reason': 'no_usable_source_group', 'coverage': coverage}
                data['materials'] = {'state': 'awaiting_input', 'reason': 'research_evidence_insufficient'}
                save('awaiting_input')
                return job['id']
            if phase == 'source_selection':
                data['memo_source_hash'] = current_hash
                data['investment_memo'] = {'state': 'source_ready', 'source_hash': current_hash,
                                           'coverage': coverage}
                save('queued', next_phase='financial_analysis')
                return job['id']
            if memo.get('state') != 'accepted':
                if phase in {'material_draft', 'material_preview', 'material_review', 'material_remediation',
                             'material_re_review', 'render'}:
                    raise ValueError('Materials require an accepted source-bound memo')
                remaining = 120 - (time.monotonic() - started)
                if remaining < 20:
                    exhausted = not can_retry()
                    data['investment_memo'] = {
                        'state': 'awaiting_input' if exhausted else 'needs_resume',
                        'reason': ('bounded_local_memo_attempts_exhausted' if exhausted
                                   else 'room_pass_time_limit'), 'coverage': coverage}
                    if exhausted:
                        data['materials'] = {'state': 'awaiting_input',
                                             'reason': 'local_memo_review_not_accepted'}
                    save('awaiting_input' if exhausted else 'queued')
                    return job['id']
                try:
                    memo_phase = ('draft_only' if phase == 'draft' else
                                  'correction_only' if phase == 'correction' else
                                  'ledger_only' if phase == 'ledger' else
                                  'review_only' if phase == 'review' else
                                  'analysis_only' if phase == 'analysis' else 'all')
                    memo = run_memo_pass(job, lead, sources, timeout=min(110, remaining - 5),
                                         inventory_digest=inventory_digest, phase=memo_phase,
                                         phase_checkpoint=data.get('memo_phase_checkpoint'))
                except TimeoutError:
                    memo = {'state': 'needs_resume', 'reason': 'private_memo_worker_timeout'}
                memo['coverage'] = coverage
                data['investment_memo'] = memo
                if memo['state'] == 'needs_resume':
                    if memo.get('memo_revision') in {'causal_v1', 'causal_v2',
                                                     'causal_v3', 'causal_v4',
                                                     'causal_v5', 'field_v1', 'stable_v1',
                                                     'field_v2'}:
                        allowed_prior = {'causal_v1': None, 'causal_v2': 'causal_v1',
                                         'causal_v3': 'causal_v2',
                                         'causal_v4': 'causal_v3',
                                         'causal_v5': 'causal_v4',
                                         'field_v1': 'causal_v5',
                                         'stable_v1': 'field_v1',
                                         'field_v2': 'stable_v1'}[memo['memo_revision']]
                        if data.get('memo_revision') != allowed_prior:
                            raise ValueError('Unknown saved memo revision')
                        from delivery.investment_memo_stage import memo_directory
                        revision_job = {**job, 'checkpoint': {
                            **job.get('checkpoint', {}),
                            'memo_revision': memo['memo_revision']}}
                        profile_path = memo_directory(revision_job) / 'model.json'
                        if not profile_path.is_file():
                            raise ValueError('Memo revision lacks frozen model profile')
                        revision_profile = json.loads(profile_path.read_text())
                        if revision_profile.get('memo_draft_contract') != data.get('memo_draft_contract'):
                            raise ValueError('Memo revision changed frozen draft contract')
                        for marker in ('memo_causal_review_contract',
                                       'memo_final_review_contract'):
                            frozen = revision_profile.get(marker)
                            if frozen is None:
                                data.pop(marker, None)
                            else:
                                data[marker] = frozen
                        data['memo_revision'] = memo['memo_revision']
                    if not can_retry():
                        data['investment_memo'] = {**memo, 'state': 'awaiting_input',
                            'reason': 'bounded_local_memo_attempts_exhausted'}
                        data['materials'] = {'state': 'awaiting_input',
                            'reason': 'local_memo_review_not_accepted'}
                        save('awaiting_input')
                    else:
                        save('queued')
                    return job['id']
                if memo['state'] == 'draft_ready' and phase == 'draft':
                    data['memo_source_hash'] = current_hash
                    data['memo_phase_checkpoint'] = memo
                    save('queued', next_phase='correction')
                    return job['id']
                if memo['state'] == 'correction_ready' and phase == 'correction':
                    data['memo_phase_checkpoint'] = memo
                    save('queued', next_phase='ledger')
                    return job['id']
                if memo['state'] == 'ledger_ready' and phase == 'ledger':
                    data['memo_phase_checkpoint'] = memo
                    save('queued', next_phase='review')
                    return job['id']
                if memo['state'] == 'accepted' and phase not in {'review', 'analysis', 'legacy'}:
                    raise ValueError('Memo accepted outside the bounded review phase')
                if memo['state'] != 'accepted':
                    data['materials'] = {'state': 'awaiting_input', 'reason': 'local_memo_validation_failed'}
                    save('awaiting_input')
                    return job['id']
                if phase == 'review':
                    from delivery.material_stage import FRESH_DRAFT_CONTRACT
                    data.setdefault('material_draft_contract', FRESH_DRAFT_CONTRACT)
                    save('queued', next_phase='material_draft')
                    return job['id']
                if phase == 'analysis':
                    save('queued', next_phase='render')
                    return job['id']
                save()
            if draft_memo_issue(coverage, memo.get('recommendation')):
                data['investment_memo'] = {**memo, 'state': 'awaiting_input',
                    'reason': 'single_source_requires_model_defer'}
                data['materials'] = {'state': 'awaiting_input',
                    'reason': 'independent_evidence_required_for_decision'}
                save('awaiting_input')
                return job['id']
            if phase == 'material_draft':
                from delivery.material_stage import (LocalMaterialModelInventoryUnavailable,
                                                     run_material_pass)
                remaining = 120 - (time.monotonic() - started)
                if remaining < 20:
                    data['materials'] = {'state': 'needs_resume',
                                         'reason': 'room_pass_time_limit'}
                    save('queued' if can_retry() else 'awaiting_input')
                    return job['id']
                try:
                    materials = run_material_pass(job, memo, timeout=min(110, remaining - 5),
                        draft_contract=data.get('material_draft_contract', 'structured_v5'))
                except LocalMaterialModelInventoryUnavailable:
                    materials = {'state': 'needs_resume',
                                 'reason': 'local_material_model_inventory_unavailable'}
                except TimeoutError:
                    materials = {'state': 'needs_resume',
                                 'reason': 'private_material_worker_timeout'}
                data['materials'] = materials
                if materials['state'] == 'needs_resume':
                    if can_retry():
                        save('queued')
                    else:
                        data['materials'] = {**materials, 'state': 'awaiting_input',
                            'reason': 'bounded_material_attempts_exhausted'}
                        save('awaiting_input')
                    return job['id']
                if materials['state'] != 'accepted':
                    save('awaiting_input')
                    return job['id']
                from delivery.material_review_stage import FRESH_REVIEW_CONTRACT
                data.setdefault('material_review_contract', FRESH_REVIEW_CONTRACT)
                save('queued', next_phase='material_preview')
                return job['id']
            if phase == 'material_preview':
                material = data.get('materials', {})
                if material.get('state') != 'accepted' or material.get('source_hash') != current_hash:
                    data['material_preview'] = {'state': 'awaiting_input',
                        'reason': 'accepted_material_specs_required_for_preview'}
                    save('awaiting_input')
                    return job['id']
                remaining = 120 - (time.monotonic() - started)
                if remaining < 20:
                    data['material_preview'] = {'state': 'needs_resume',
                        'reason': 'room_pass_time_limit'}
                    save('queued' if can_retry() else 'awaiting_input')
                    return job['id']
                try:
                    frozen, scope = frozen_material_preview(job, memo, material,
                        room.company_name, timeout=min(110, remaining - 5))
                except TimeoutError:
                    data['material_preview'] = {'state': 'needs_resume',
                        'reason': 'private_material_preview_worker_timeout'}
                    save('queued' if can_retry() else 'awaiting_input')
                    return job['id']
                save()  # Recheck the lease before publishing private draft slots.
                current_room = store.get_workspace(job['tenant_id'], workspace_id=room.id)
                if current_room is None or revision_for(store, current_room) != job['input_revision']:
                    raise ValueError('Material preview input revision changed before registration')
                artifact_ids = [register_draft(store.conn, job['tenant_id'], room.id,
                    kind, fmt, job['input_revision'], (frozen / name).read_bytes(), job=job)
                    for name, kind, fmt in PREVIEW_FILES]
                data['material_preview'] = {**scope, 'state': 'accepted',
                                            'artifact_ids': artifact_ids}
                save('queued', next_phase='material_review')
                return job['id']
            if phase == 'material_review':
                from delivery.material_review_stage import run_material_review_pass
                material = data.get('materials', {})
                if material.get('state') != 'accepted' or material.get('source_hash') != current_hash:
                    data['material_review'] = {'state': 'awaiting_input',
                        'reason': 'accepted_material_specs_required_for_review'}
                    save('awaiting_input')
                    return job['id']
                remaining = 120 - (time.monotonic() - started)
                if remaining < 20:
                    data['material_review'] = {'state': 'needs_resume',
                        'reason': 'room_pass_time_limit'}
                    save('queued' if can_retry() else 'awaiting_input')
                    return job['id']
                try:
                    review = run_material_review_pass(job, memo, material,
                        timeout=min(110, remaining - 5),
                        review_contract=data.get('material_review_contract'))
                except TimeoutError:
                    review = {'state': 'needs_resume',
                              'reason': 'private_material_review_worker_timeout'}
                data['material_review'] = review
                if review['state'] == 'needs_resume':
                    if can_retry():
                        save('queued')
                    else:
                        data['material_review'] = {**review, 'state': 'awaiting_input',
                            'reason': 'bounded_material_review_attempts_exhausted'}
                        save('awaiting_input')
                    return job['id']
                if review['state'] != 'accepted':
                    if (review['state'] == 'blocked' and review.get('response_id') and
                            review.get('review', {}).get('findings')):
                        save('queued', next_phase='material_remediation')
                        return job['id']
                    save('awaiting_input')
                    return job['id']
                save('queued', next_phase='render')
                return job['id']
            if phase == 'material_remediation':
                from delivery.material_repair_stage import run_material_repair_pass
                material = data.get('materials', {})
                blocked_review = data.get('material_review', {})
                if (material.get('state') != 'accepted' or
                        blocked_review.get('state') != 'blocked' or
                        not blocked_review.get('review', {}).get('findings')):
                    data['material_repair'] = {'state': 'awaiting_input',
                        'reason': 'quote_bound_review_block_required_for_repair'}
                    save('awaiting_input')
                    return job['id']
                remaining = 120 - (time.monotonic() - started)
                if remaining < 20:
                    data['material_repair'] = {'state': 'awaiting_input',
                        'reason': 'material_repair_pass_time_limit'}
                    save('awaiting_input')
                    return job['id']
                try:
                    repair = run_material_repair_pass(job, memo, material, blocked_review,
                        timeout=min(110, remaining - 5))
                except TimeoutError:
                    repair = {'state': 'blocked',
                              'reason': 'private_material_repair_worker_timeout'}
                data['material_repair'] = repair
                if repair['state'] not in {'accepted', 'disputed_without_change'}:
                    save('awaiting_input')
                    return job['id']
                save('queued', next_phase='material_re_review')
                return job['id']
            if phase == 'material_re_review':
                from delivery.material_review_stage import run_material_review_pass
                repair = data.get('material_repair', {})
                if repair.get('state') not in {'accepted', 'disputed_without_change'}:
                    data['material_re_review'] = {'state': 'awaiting_input',
                        'reason': 'accepted_material_repair_required'}
                    save('awaiting_input')
                    return job['id']
                remaining = 120 - (time.monotonic() - started)
                if remaining < 20:
                    data['material_re_review'] = {'state': 'needs_resume',
                        'reason': 'room_pass_time_limit'}
                    save('queued' if can_retry() else 'awaiting_input')
                    return job['id']
                try:
                    review = run_material_review_pass(job, memo, repair,
                        timeout=min(110, remaining - 5), repaired=True,
                        review_contract=data.get('material_review_contract'))
                except TimeoutError:
                    review = {'state': 'needs_resume',
                              'reason': 'private_material_re_review_worker_timeout'}
                data['material_re_review'] = review
                if review['state'] == 'needs_resume':
                    if can_retry():
                        save('queued')
                    else:
                        data['material_re_review'] = {**review, 'state': 'awaiting_input',
                            'reason': 'bounded_material_re_review_attempts_exhausted'}
                        save('awaiting_input')
                    return job['id']
                if review['state'] != 'accepted':
                    save('awaiting_input')
                    return job['id']
                save('queued', next_phase='render')
                return job['id']
            if data.get('materials', {}).get('state') != 'draft':
                material = data.get('materials', {})
                if (material.get('state') != 'accepted' or
                        material.get('source_hash') != current_hash):
                    data['materials'] = {'state': 'awaiting_input',
                                         'reason': 'model_authored_material_specs_required'}
                    save('awaiting_input')
                    return job['id']
                from delivery.material_stage import validate_material_checkpoint
                validate_material_checkpoint(job, memo, material)
                from delivery.material_review_stage import validate_material_review_checkpoint
                if data.get('material_repair', {}).get('state') in {
                        'accepted', 'disputed_without_change'}:
                    if data.get('material_re_review', {}).get('state') != 'accepted':
                        raise ValueError('Repaired material lacks passing frozen re-review')
                    from delivery.material_repair_stage import validate_material_repair_checkpoint
                    material = validate_material_repair_checkpoint(job, memo,
                        data['material_repair'])
                    validate_material_review_checkpoint(job, memo, material,
                        data.get('material_re_review'), repaired=True)
                else:
                    if data.get('material_review', {}).get('state') != 'accepted':
                        raise ValueError('Material lacks passing frozen semantic review')
                    validate_material_review_checkpoint(job, memo, material,
                        data.get('material_review'))
                remaining = 120 - (time.monotonic() - started)
                if remaining < 15:
                    save('queued' if can_retry() else 'awaiting_input')
                    return job['id']
                with tempfile.TemporaryDirectory(prefix='private-render-') as directory:
                    root=Path(directory)
                    (root/'request.json').write_text(json.dumps({'operation':'render','title':room.company_name,
                        'memo_sections':data['investment_memo']['sections'],
                        'intro_sections':material['decks']['intro_deck']['sections'],
                        'pitch_sections':material['decks']['pitch_deck']['sections']}))
                    font_root=Path('/Applications/LibreOffice.app/Contents/Resources/fonts/truetype')
                    run_private([sys.executable,SCRIPT],root,timeout=max(1,remaining-5),
                        extra_read=(font_root,) if font_root.is_dir() else ())
                    save()  # Check lease/access after child execution, before publication.
                    artifacts=[]
                    for name,kind,fmt in [('intro.pptx','intro_deck','pptx'),('intro.pdf','intro_deck','pdf'),
                                          ('pitch.pptx','pitch_deck','pptx'),('pitch.pdf','pitch_deck','pdf'),
                                          ('memo.docx','investment_memorandum','docx'),
                                          ('memo.pdf','investment_memorandum','pdf'),
                                          ('research.pdf','research_brief','pdf')]:
                        artifacts.append(register_draft(store.conn,job['tenant_id'],room.id,kind,fmt,job['input_revision'],(root/name).read_bytes(),job=job))
                data['materials']={**material, 'state':'draft', 'artifact_ids':artifacts}
            blockers = ['complete_formats_calculation_layout_and_exact_version_reviews_required']
            if source_groups < 2:
                blockers.append('independent_evidence_required_for_release')
            if data['financial_model']['state'] != 'validated':
                blockers.append('financial_model_not_validated')
            data['validation']={'state':'blocked','reason':blockers[0], 'blockers':blockers}
            save('awaiting_input')
        except Exception as exc:
            try:jobs.checkpoint(store.conn,job,data,state='blocked',error=type(exc).__name__)
            except (PermissionError,ValueError):pass
        return job['id']
