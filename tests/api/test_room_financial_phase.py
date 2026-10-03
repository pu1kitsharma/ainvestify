"""Finite room financial orchestration over synthetic workbook uploads only."""
from __future__ import annotations

import json

from agents.research.investment_memo import Source
from delivery.worker import process_one
from schemas import Deal, Document
from store import Store
from tests.api.test_authentication import secured, sign_in


def ready_sources(monkeypatch):
    from delivery import investment_memo_stage
    sources = [Source(id='S1', url='https://one.example/company', title='One',
        passage='Synthetic company source evidence.', version='version-1',
        attribution='One synthetic publisher'),
        Source(id='S2', url='https://two.example/company', title='Two',
        passage='Independent synthetic company evidence.', version='version-1',
        attribution='Second synthetic publisher')]
    coverage = {'source_count': 2, 'public_publishers': 2, 'private_documents': 0,
        'coverage_complete': True, 'omitted_passages': 0, 'oversized_passages': 0}
    monkeypatch.setattr(investment_memo_stage, 'room_sources',
        lambda *args, **kwargs: (sources, coverage))


def room_job(secured, monkeypatch, tmp_path, workbook_bytes=None):
    client, db, users = secured
    sign_in(client, users[0])
    created = client.post('/api/rooms', json={
        'name': 'Synthetic private company',
        'website': 'https://synthetic.example'}).json()
    tenant = users[0][1]
    with Store(db) as store:
        lead = store.get_lead(tenant, created['lead_id'])
        deal = Deal(tenant_id=tenant, name='Synthetic private company')
        store.save_deal(deal)
        lead.promoted_deal_id = deal.id
        store.save_lead(lead)
        room = store.get_workspace(tenant, workspace_id=created['workspace_id'])
        room.deal_id = deal.id
        store.save_workspace(room, expected_revision=room.revision)
        if workbook_bytes is not None:
            source = tmp_path / 'synthetic.xlsx'
            source.write_bytes(workbook_bytes)
            document = Document(id='synthetic-document', tenant_id=tenant,
                deal_id=deal.id, filename=source.name, type='xlsx', storage_uri=str(source))
            store.save_document(document)
    ready_sources(monkeypatch)
    activated = client.post(f"/api/rooms/from-lead/{created['lead_id']}/activate")
    assert activated.status_code == 202, activated.text
    return client, db, created['workspace_id'], activated.json()['job']['id']


def checkpoint(db, job_id):
    with Store(db) as store:
        row = store.conn.execute('SELECT phase,phase_attempt,attempt,state,checkpoint '
            'FROM room_jobs WHERE id=?', (job_id,)).fetchone()
    return {'phase': row[0], 'phase_attempt': row[1], 'attempt': row[2],
            'state': row[3], **json.loads(row[4])}


def test_no_workbook_advances_to_draft_with_financial_disclosure(secured, monkeypatch, tmp_path):
    client, db, room_id, job_id = room_job(secured, monkeypatch, tmp_path)
    assert process_one(db) == job_id
    assert checkpoint(db, job_id)['phase'] == 'financial_analysis'
    assert process_one(db) == job_id
    saved = checkpoint(db, job_id)
    assert saved['phase'] == 'draft' and saved['state'] == 'queued'
    assert saved['financial_analysis']['state'] == 'awaiting_input'
    assert saved['financial_model']['state'] == 'awaiting_input'
    reopened = client.get(f'/api/rooms/{room_id}').json()
    assert reopened['jobs'][0]['id'] == job_id
    assert checkpoint(db, job_id)['attempt'] == 2


def test_broken_workbook_does_not_block_core_memo_phase(secured, monkeypatch, tmp_path):
    from delivery import financial_stage
    client, db, _, job_id = room_job(secured, monkeypatch, tmp_path,
        b'synthetic broken workbook package')
    calls = []
    def blocked(store, job, document, **kwargs):
        calls.append(document.id)
        return {'state': 'blocked', 'reason': 'invalid_or_unsafe_workbook_package',
                'financial_validation': 'not_established'}
    monkeypatch.setattr(financial_stage, 'run_financial_stage', blocked)
    # Inventory is already a durable private checkpoint; no parser is needed in this test.
    with Store(db) as store:
        store.conn.execute('UPDATE room_jobs SET checkpoint=? WHERE id=?',
            (json.dumps({'workbooks': {'synthetic-document': {'findings': []}}}), job_id))
        store.conn.commit()
    assert process_one(db) == job_id
    assert process_one(db) == job_id
    saved = checkpoint(db, job_id)
    assert saved['phase'] == 'draft' and saved['state'] == 'queued'
    assert saved['financial_model']['state'] == 'blocked'
    assert saved['financial_analysis']['documents']['synthetic-document']['reason'] == (
        'invalid_or_unsafe_workbook_package')
    assert calls == ['synthetic-document']


def test_resumed_workbook_finishes_once_and_reopen_does_not_repeat_inference(
        secured, monkeypatch, tmp_path):
    from delivery import financial_stage
    client, db, room_id, job_id = room_job(secured, monkeypatch, tmp_path,
        b'synthetic workbook bytes handled by a fake private worker')
    calls = []
    def resumable(store, job, document, **kwargs):
        calls.append((document.id, kwargs['budget_seconds']))
        if len(calls) == 1:
            return {'state': 'needs_resume', 'reason': 'findings_pending',
                    'financial_validation': 'not_established'}
        return {'state': 'partial_evidence', 'findings': [
            {'text': 'Synthetic model-authored finding'}],
            'financial_validation': 'not_established'}
    monkeypatch.setattr(financial_stage, 'run_financial_stage', resumable)
    with Store(db) as store:
        store.conn.execute('UPDATE room_jobs SET checkpoint=? WHERE id=?',
            (json.dumps({'workbooks': {'synthetic-document': {'findings': []}}}), job_id))
        store.conn.commit()
    for expected in ('financial_analysis', 'financial_analysis', 'draft'):
        assert process_one(db) == job_id
        assert checkpoint(db, job_id)['phase'] == expected
    saved = checkpoint(db, job_id)
    assert saved['financial_model']['state'] == 'partial_evidence'
    assert saved['financial_model']['state'] != 'validated'
    assert saved['financial_analysis']['documents']['synthetic-document']['findings'] == [
        {'text': 'Synthetic model-authored finding'}]
    assert calls == [('synthetic-document', 105), ('synthetic-document', 105)]
    # Activation and room view preserve the same queued job/revision; no extra pass runs.
    with Store(db) as store:
        lead_id = store.get_workspace(secured[2][0][1], workspace_id=room_id).lead_id
    reopened = client.post(f'/api/rooms/from-lead/{lead_id}/activate').json()
    assert reopened['job']['id'] == job_id
    assert len(calls) == 2
