from tests.api.test_authentication import secured, sign_in
from api.routers.rooms import revision_for
from delivery.worker import process_one
from delivery.artifacts import register_draft, artifact_root
from delivery.storage import scope_component
from delivery.rendering import render_intro
from store import Store
from types import SimpleNamespace


def test_room_revision_binds_actual_local_memo_role_configuration(monkeypatch):
    workspace = SimpleNamespace(tenant_id='tenant', lead_id='lead', deal_id=None,
        metric_updates=[], company_analysis={'inputs': {}}, metric_imports=[])
    lead = SimpleNamespace(company_profile=None, promoted_deal_id=None)
    store = SimpleNamespace(get_lead=lambda tenant, lead_id: lead)
    monkeypatch.setenv('PREPARATION_MODEL', 'qwen3.5:9b')
    monkeypatch.delenv('LOCAL_MEMO_DRAFT_MODEL', raising=False)
    monkeypatch.delenv('LOCAL_MEMO_PART_B_MODEL', raising=False)
    monkeypatch.delenv('LOCAL_MEMO_REVIEW_MODEL', raising=False)
    base = revision_for(store, workspace)
    monkeypatch.setenv('LOCAL_MEMO_PART_B_MODEL', 'qwen3.5:4b')
    assert revision_for(store, workspace) != base
    monkeypatch.delenv('LOCAL_MEMO_PART_B_MODEL')
    monkeypatch.setenv('LOCAL_MEMO_DRAFT_MODEL', 'qwen3.5:4b')
    assert revision_for(store, workspace) != base
    monkeypatch.delenv('LOCAL_MEMO_DRAFT_MODEL')
    monkeypatch.setenv('LOCAL_MEMO_REVIEW_MODEL', 'qwen3:14b')
    assert revision_for(store, workspace) != base


def test_direct_entry_activation_reopen_worker_and_cross_tenant(secured):
    client,db,users=secured
    sign_in(client,users[0])
    response=client.post('/api/rooms',json={'name':'Synthetic private company','website':'https://synthetic.example'})
    assert response.status_code==201,response.text
    created=response.json();room_id=created['workspace_id']
    repeated=client.post(f"/api/rooms/from-lead/{created['lead_id']}/activate").json()
    assert repeated['job']['id']==created['job']['id']
    assert process_one(db)==created['job']['id']
    state=client.get(f'/api/rooms/{room_id}').json()
    assert state['jobs'][0]['state']=='awaiting_input'
    assert state['jobs'][0]['checkpoint']['materials']['state']=='awaiting_input'
    assert client.post(f"/api/rooms/from-lead/{created['lead_id']}/activate").json()['job']['id']==created['job']['id']
    with Store(db) as s:
        lead=s.get_lead(users[0][1],created['lead_id'])
        assert lead.company_profile.provenance['origin']=='manual'
        assert not lead.discovery_signals
    sign_in(client,users[1])
    assert client.get(f'/api/rooms/{room_id}').status_code==404
    assert client.post(f"/api/rooms/from-lead/{created['lead_id']}/activate").status_code==404


def test_room_memo_phases_have_separate_finite_budgets(secured, monkeypatch):
    from agents.research.investment_memo import Source
    from delivery import investment_memo_stage
    client, db, users = secured
    sign_in(client, users[0])
    created = client.post('/api/rooms', json={
        'name': 'Synthetic private company', 'website': 'https://synthetic.example'}).json()
    sources = [Source(id='S1', url='https://one.example/company', title='One',
        passage='Synthetic company record with dated source evidence.', version='version-1',
        attribution='Synthetic public source'),
        Source(id='S2', url='https://two.example/company', title='Two',
        passage='Independent synthetic company record with dated source evidence.',
        version='version-1', attribution='Second synthetic public source')]
    coverage = {'source_count': 2, 'public_publishers': 2, 'private_documents': 0,
        'coverage_complete': True, 'omitted_passages': 0, 'oversized_passages': 0}
    monkeypatch.setattr(investment_memo_stage, 'room_sources',
        lambda *args, **kwargs: (sources, coverage))
    calls = []
    def fake_memo(job, lead, bound_sources, *, timeout, inventory_digest=None,
                  phase='all', phase_checkpoint=None):
        calls.append(phase)
        assert bound_sources == sources
        source_hash = investment_memo_stage.source_fingerprint(job, lead, bound_sources)
        if phase == 'draft_only' and calls.count('draft_only') < 3:
            return {'state': 'needs_resume', 'reason': 'synthetic_bounded_draft'}
        if phase == 'draft_only':
            return {'state': 'draft_ready', 'draft': {'part_a_response_id': 'a',
                'part_b_response_id': 'b'}, 'source_hash': source_hash}
        if phase == 'correction_only':
            assert phase_checkpoint['state'] == 'draft_ready'
            return {'state': 'correction_ready', 'source_hash': source_hash,
                    'corrected_memo_digest': 'c', 'source_set_digest': 's', 'as_of_date': '2026-10-03'}
        if phase == 'ledger_only':
            assert phase_checkpoint['state'] == 'correction_ready'
            return {'state': 'ledger_ready', 'source_hash': source_hash,
                    'corrected_memo_digest': 'c', 'source_set_digest': 's', 'as_of_date': '2026-10-03',
                    'ledger_binding_digest': 'l', 'final_memo_digest': 'f'}
        assert phase == 'review_only' and phase_checkpoint['state'] == 'ledger_ready'
        return {'state': 'accepted', 'recommendation': 'defer_pending_evidence',
            'sections': [('Summary', 'Synthetic model-authored text', 'Synthetic source')],
            'source_hash': source_hash}
    monkeypatch.setattr(investment_memo_stage, 'run_memo_pass', fake_memo)
    for expected_phase in ('financial_analysis', 'draft', 'draft', 'draft', 'correction', 'ledger', 'review',
                           'material_draft'):
        assert process_one(db) == created['job']['id']
        with Store(db) as store:
            job = store.conn.execute('SELECT phase,phase_attempt,attempt,state FROM room_jobs WHERE id=?',
                (created['job']['id'],)).fetchone()
        assert job[0] == expected_phase
        assert job[3] == 'queued'
    assert calls == ['draft_only', 'draft_only', 'draft_only', 'correction_only',
                     'ledger_only', 'review_only']
    assert job[2] == 8 and job[1] == 0


def test_private_preview_integrity_and_fail_closed_release(secured,tmp_path,monkeypatch):
    client,db,users=secured
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT',str(tmp_path/'artifacts'))
    sign_in(client,users[0])
    created=client.post('/api/rooms',json={'name':'Synthetic company','website':'https://synthetic.example'}).json()
    room_id=created['workspace_id']
    with Store(db) as s:
        room=s.get_workspace(users[0][1],workspace_id=room_id)
        content=render_intro('Synthetic fixture',[('Synthetic only','Recorded fixture text','Synthetic source')])
        artifact=register_draft(s.conn,users[0][1],room_id,'intro_deck','pptx',revision_for(s,room),content)
    base=f'/api/rooms/{room_id}/artifacts/{artifact}'
    assert client.get(base+'/preview').content==content
    assert client.get(base+'/download').status_code==409
    report=client.post(f'/api/rooms/{room_id}/validate')
    assert report.status_code==200,report.text
    assert report.json()['eligible_for_release'] is False
    assert client.post(f"/api/rooms/{room_id}/packages/{report.json()['package_id']}/release").status_code==409
    sign_in(client,users[1]);assert client.get(base+'/preview').status_code==404
    sign_in(client,users[0])
    import hashlib
    path=artifact_root()/scope_component(users[0][1])/scope_component(room_id)/hashlib.sha256(content).hexdigest()
    path.write_bytes(b'modified')
    assert client.get(base+'/preview').status_code==409


def test_authenticated_legacy_preparation_route_queues_durable_work(secured,monkeypatch):
    client,db,users=secured;sign_in(client,users[0])
    created=client.post('/api/rooms',json={'name':'Synthetic company','website':'https://synthetic.example'}).json()
    def forbidden(*args,**kwargs):raise AssertionError('BackgroundTasks must not run authenticated room preparation')
    monkeypatch.setattr('api.routers.operations._prepare_job',forbidden)
    response=client.post(f"/api/operations/leads/{created['lead_id']}/preparation-jobs")
    assert response.status_code==202,response.text
    assert response.json()['automation']['id']==created['job']['id']
    with Store(db) as store:
        assert store.get_workspace(users[0][1],workspace_id=created['workspace_id']).automation.worker_id=='durable-room'


def test_source_version_changes_on_modified_bytes_and_recorded_inventory(tmp_path):
    from api.routers.rooms import document_input_version
    from schemas import Document
    path=tmp_path/'fixture.xlsx';path.write_bytes(b'synthetic original')
    document=Document(id='doc',tenant_id='tenant',deal_id='deal',filename=path.name,type='xlsx',storage_uri=str(path))
    first=document_input_version(document)
    assert document_input_version(document)==first
    path.write_bytes(b'synthetic changed')
    second=document_input_version(document)
    assert second!=first
    document.workbook_inventory={'formula_count':1}
    assert document_input_version(document)!=second
    path.unlink();path.symlink_to(tmp_path/'unavailable')
    assert document_input_version(document)['source']=={'state':'unavailable_or_unsafe'}
