from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from store import Store
from security.identity import provision_verified_identity
from delivery.jobs import enqueue,claim,checkpoint,cancel,list_jobs
from delivery.workflow_contracts import DealRoomActivated
from delivery.jobs import _phase_cap


def setup(db):
    with Store(db) as s:
        user,tenant=provision_verified_identity(s.conn,'https://accounts.google.com','synthetic')
    return DealRoomActivated(actor_id=user,tenant_id=tenant,workspace_id='room',input_revision='a'*64,workflow_version='v1')


@pytest.mark.parametrize("workflow", ["room-v27-rationale-content-gate", "room-v28-scope-content-gate",
                                      "room-v29-blind-scope-content-gate", "room-v30-author-scope-content-gate", "room-v31-blind-author-content-gate", "room-v32-source-unit-content-gate", "room-v33-isolated-source-unit-content-gate", "room-v34-isolated-source-unit-content-gate", "room-v35-isolated-source-unit-content-gate", "room-v36-isolated-source-unit-content-gate", "room-v37-isolated-source-unit-content-gate", "room-v38-full-memo-content-gate", "room-v39-checkpointed-full-memo-gate", "room-v40-native-claim-full-memo-gate", "room-v41-structured-section-full-memo-gate", "room-v42-independent-author-checkpoints", "room-v43-bounded-section-author", "room-v44-literal-narrative-author", "room-v45-narrative-section-budget", "room-v46-structured-core-decisions", "room-v47-prospective-risk-scope", "room-v48-narrative-function-review", "room-v49-batched-material-review", "room-v50-complete-narrative-materials", "room-v51-temporal-material-scope", "room-v52-compact-material-selector", "room-v53-attributed-period-selector"])
def test_fresh_workflow_gate_is_frozen_across_checkpoints(tmp_path, workflow):
    db = tmp_path / 'jobs.db'
    event = setup(db).model_copy(update={'workflow_version': workflow})
    with Store(db) as store:
        queued = enqueue(store.conn, event)
        assert queued['checkpoint']['workflow_contract'] == event.workflow_version
        running = claim(store.conn, now=100, lease_seconds=20)
        checkpoint(store.conn, running, {'evidence': 'saved'}, now=101)
        resumed = list_jobs(store.conn, event.tenant_id, event.workspace_id)[0]
        assert resumed['checkpoint'] == {'evidence': 'saved', 'workflow_contract': event.workflow_version}
        with pytest.raises(ValueError, match='cannot change'):
            checkpoint(store.conn, resumed, {'workflow_contract': 'room-v26'}, now=102)


@pytest.mark.parametrize("workflow", ["room-v27-rationale-content-gate", "room-v28-scope-content-gate",
                                      "room-v29-blind-scope-content-gate", "room-v30-author-scope-content-gate", "room-v31-blind-author-content-gate", "room-v32-source-unit-content-gate", "room-v33-isolated-source-unit-content-gate", "room-v34-isolated-source-unit-content-gate", "room-v35-isolated-source-unit-content-gate", "room-v36-isolated-source-unit-content-gate", "room-v37-isolated-source-unit-content-gate", "room-v38-full-memo-content-gate", "room-v39-checkpointed-full-memo-gate", "room-v40-native-claim-full-memo-gate", "room-v41-structured-section-full-memo-gate", "room-v42-independent-author-checkpoints", "room-v43-bounded-section-author", "room-v44-literal-narrative-author", "room-v45-narrative-section-budget", "room-v46-structured-core-decisions", "room-v47-prospective-risk-scope", "room-v48-narrative-function-review", "room-v49-batched-material-review", "room-v50-complete-narrative-materials", "room-v51-temporal-material-scope", "room-v52-compact-material-selector", "room-v53-attributed-period-selector"])
def test_fresh_workflow_cannot_skip_content_phase(workflow):
    from delivery.jobs import _next_phase
    job = {'phase': 'review', 'phase_attempt': 1,
           'checkpoint': {'workflow_contract': workflow}}
    with pytest.raises(ValueError, match='content review phase'):
        _next_phase(job, 'material_draft')
    assert _next_phase(job, 'content_review') == ('content_review', 0)
    assert _next_phase({**job, 'checkpoint': {}}, 'material_draft') == ('material_draft', 0)


def test_versioned_causal_revision_review_cap_is_finite():
    base = {'phase': 'review', 'checkpoint': {
        'memo_draft_contract': 'memo-cards-v13',
        'memo_causal_review_contract': 'memo-causal-v2'}}
    assert _phase_cap(base) == 14
    assert _phase_cap({**base, 'checkpoint': {**base['checkpoint'],
                       'memo_revision': 'causal_v1'}}) == 14
    for revision in ('causal_v2', 'causal_v3', 'causal_v4', 'causal_v5'):
        assert _phase_cap({**base, 'checkpoint': {**base['checkpoint'],
                           'memo_revision': revision}}) == 28
    stable = {**base['checkpoint'], 'memo_causal_review_contract': 'memo-causal-v3',
              'memo_final_review_contract': 'field_v4'}
    for revision in ('stable_v1', 'field_v2'):
        assert _phase_cap({**base, 'checkpoint': {**stable,
                           'memo_revision': revision}}) == 28


def test_concurrent_activation_restart_and_fencing(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    def submit(_):
        with Store(db) as s:return enqueue(s.conn,event)['id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(submit,range(8))))==1
    with Store(db) as s:
        first=claim(s.conn,now=100,lease_seconds=10)
        checkpoint(s.conn,first,{'evidence':'saved'},now=101)
        assert claim(s.conn,now=102) is None
    with Store(db) as s:
        resumed=claim(s.conn,now=111)
        assert resumed['checkpoint']=={'evidence':'saved'}
        assert resumed['attempt']==2
        with pytest.raises(ValueError):checkpoint(s.conn,first,{},now=112)
        checkpoint(s.conn,resumed,{'evidence':'saved'},state='completed',now=112)
        assert enqueue(s.conn,event)['state']=='completed'


def test_revoked_and_cancelled_jobs_cannot_finalize(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as s:
        job=enqueue(s.conn,event);running=claim(s.conn)
        cancel(s.conn,event.tenant_id,job['id'])
        with pytest.raises(ValueError):checkpoint(s.conn,running,{},state='completed')
        changed=event.model_copy(update={'input_revision':'b'*64})
        enqueue(s.conn,changed);running=claim(s.conn)
        s.conn.execute('UPDATE auth_memberships SET active=0');s.conn.commit()
        with pytest.raises(PermissionError):checkpoint(s.conn,running,{},state='completed')
        assert list_jobs(s.conn,'another-tenant','room')==[]


def test_expiry_retries_are_bounded(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as s:
        enqueue(s.conn,event)
        for now in (100,111,122):assert claim(s.conn,now=now,lease_seconds=10)
        assert claim(s.conn,now=133) is None
        assert list_jobs(s.conn,event.tenant_id,event.workspace_id)[0]['state']=='failed'


@pytest.mark.parametrize('contract,cap', [(None, 6), ('memo-cards-v1', 8),
                                          ('memo-cards-v2', 8), ('memo-cards-v3', 8),
                                          ('memo-cards-v4', 8), ('memo-cards-v5', 8),
                                          ('memo-cards-v6', 8), ('memo-cards-v7', 8),
                                          ('memo-cards-v8', 30), ('memo-cards-v9', 30),
                                          ('memo-cards-v10', 30), ('memo-cards-v11', 30),
                                          ('memo-cards-v12', 30), ('memo-cards-v13', 30)])
def test_draft_lease_reclaim_respects_frozen_packet_cap(tmp_path, contract, cap):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        checkpoint_value = {} if contract is None else {'memo_draft_contract': contract}
        store.conn.execute("UPDATE room_jobs SET phase='draft',checkpoint=? WHERE work_key=?",
            (json.dumps(checkpoint_value), event.idempotency_key()))
        store.conn.commit()
        for index in range(cap):
            job=claim(store.conn,now=100 + 11*index,lease_seconds=10)
            assert (job['phase'],job['phase_attempt']) == ('draft',index+1)
        assert claim(store.conn,now=100 + 11*cap) is None
        assert list_jobs(store.conn,event.tenant_id,event.workspace_id)[0]['state']=='failed'


@pytest.mark.parametrize('contract,causal,cap', [(None, None, 2), ('memo-cards-v2', None, 2),
                                                 ('memo-cards-v3', None, 2),
                                                 ('memo-cards-v3', 'memo-causal-v1', 14),
                                                 ('memo-cards-v3', 'memo-causal-v2', 14),
                                                 ('memo-cards-v4', None, 2),
                                                 ('memo-cards-v4', 'memo-causal-v2', 14),
                                                 ('memo-cards-v5', None, 2),
                                                 ('memo-cards-v5', 'memo-causal-v2', 14),
                                                 ('memo-cards-v8', None, 2),
                                                 ('memo-cards-v8', 'memo-causal-v2', 14),
                                                 ('memo-cards-v9', None, 2),
                                                 ('memo-cards-v9', 'memo-causal-v2', 14),
                                                 ('memo-cards-v10', None, 2),
                                                 ('memo-cards-v10', 'memo-causal-v2', 14),
                                                 ('memo-cards-v11', None, 2),
                                                 ('memo-cards-v11', 'memo-causal-v2', 14),
                                                 ('memo-cards-v12', None, 2),
                                                 ('memo-cards-v12', 'memo-causal-v2', 14),
                                                 ('memo-cards-v13', None, 2),
                                                 ('memo-cards-v13', 'memo-causal-v2', 14)])
def test_review_lease_reclaim_respects_frozen_causal_cap(tmp_path, contract, causal, cap):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        checkpoint_value = {} if contract is None else {'memo_draft_contract': contract}
        if causal:
            checkpoint_value['memo_causal_review_contract'] = causal
        store.conn.execute("UPDATE room_jobs SET phase='review',checkpoint=? WHERE work_key=?",
            (json.dumps(checkpoint_value), event.idempotency_key()))
        store.conn.commit()
        for index in range(cap):
            job=claim(store.conn,now=100 + 11*index,lease_seconds=10)
            assert (job['phase'],job['phase_attempt']) == ('review',index+1)
        assert claim(store.conn,now=100 + 11*cap) is None
        assert list_jobs(store.conn,event.tenant_id,event.workspace_id)[0]['state']=='failed'


def test_changed_inputs_fence_obsolete_work(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as s:
        old=enqueue(s.conn,event);lease=claim(s.conn)
        new=enqueue(s.conn,event.model_copy(update={'input_revision':'c'*64}))
        assert new['id']!=old['id']
        assert new['state']=='queued'
        with pytest.raises(ValueError):checkpoint(s.conn,lease,{},state='completed')
        assert next(j for j in list_jobs(s.conn,event.tenant_id,event.workspace_id) if j['id']==old['id'])['state']=='cancelled'


def test_bounded_yield_preserves_checkpoint_and_fences_old_lease(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        first=claim(store.conn)
        checkpoint(store.conn,first,{'memo':'draft_recorded'},state='queued')
        second=claim(store.conn)
        assert second['attempt']==2
        assert second['checkpoint']=={'memo':'draft_recorded'}
        with pytest.raises(ValueError):checkpoint(store.conn,first,{},state='completed')
        checkpoint(store.conn,second,{'memo':'review_recorded'},state='queued')
        third=claim(store.conn)
        assert third['attempt']==3
        with pytest.raises(ValueError,match='3 bounded source_selection passes'):
            checkpoint(store.conn,third,{},state='queued')


def test_phases_have_independent_finite_attempts_and_monotonic_audit(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        expected_attempt=0
        for phase_name, cap, next_phase in (
            ('source_selection',3,'financial_analysis'),
            ('financial_analysis',9,'draft'), ('draft',6,'correction'),
            ('correction',3,'ledger'), ('ledger',5,'review'),
            ('review',2,'content_review'), ('content_review',3,'material_draft'), ('material_draft',6,'material_preview'),
            ('material_preview',2,'material_review'),
            ('material_review',2,'material_remediation'),
            ('material_remediation',1,'material_re_review'),
            ('material_re_review',2,'render'),
            ('render',1,None),
        ):
            for phase_attempt in range(1,cap+1):
                job=claim(store.conn)
                expected_attempt+=1
                assert (job['phase'],job['phase_attempt'],job['attempt'])==(phase_name,phase_attempt,expected_attempt)
                if phase_attempt<cap:
                    checkpoint(store.conn,job,{'phase':phase_name},state='queued')
                elif next_phase:
                    checkpoint(store.conn,job,{'phase':phase_name},state='queued',phase=next_phase)
                else:
                    with pytest.raises(ValueError,match='render pass'):
                        checkpoint(store.conn,job,{},state='queued')
                    checkpoint(store.conn,job,{'phase':phase_name},state='completed')
        assert expected_attempt==45
        assert claim(store.conn) is None
        assert enqueue(store.conn,event)['attempt']==45


def test_expired_material_lease_reclaims_through_sixth_attempt_only(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        store.conn.execute("UPDATE room_jobs SET phase='material_draft' WHERE work_key=?",
                           (event.idempotency_key(),))
        store.conn.commit()
        for expected, now in enumerate((100, 111, 122, 133, 144, 155), 1):
            job=claim(store.conn,now=now,lease_seconds=10)
            assert job['phase_attempt']==expected
        assert claim(store.conn,now=166) is None
        job=list_jobs(store.conn,event.tenant_id,event.workspace_id)[0]
        assert (job['phase_attempt'],job['state'])==(6,'failed')


def test_expired_ledger_lease_reclaims_through_fifth_attempt_only(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        store.conn.execute("UPDATE room_jobs SET phase='ledger' WHERE work_key=?",
                           (event.idempotency_key(),))
        store.conn.commit()
        for expected, now in enumerate((100, 111, 122, 133, 144), 1):
            running=claim(store.conn,now=now,lease_seconds=10)
            assert (running['attempt'],running['phase_attempt'])==(expected,expected)
        assert claim(store.conn,now=155) is None
        job=list_jobs(store.conn,event.tenant_id,event.workspace_id)[0]
        assert (job['attempt'],job['phase_attempt'],job['state'])==(5,5,'failed')


def test_phase_transition_requires_current_lease_and_order(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        first=claim(store.conn)
        with pytest.raises(ValueError,match='in order'):
            checkpoint(store.conn,first,{},state='queued',phase='analysis')
        checkpoint(store.conn,first,{},state='queued',phase='financial_analysis')
        second=claim(store.conn)
        assert (second['attempt'],second['phase_attempt'])==(2,1)
        with pytest.raises(ValueError):
            checkpoint(store.conn,first,{},state='queued',phase='financial_analysis')
        with pytest.raises(ValueError,match='queued checkpoint'):
            checkpoint(store.conn,second,{},state='completed',phase='analysis')


def test_lease_expiry_is_bounded_per_phase(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        enqueue(store.conn,event)
        first=claim(store.conn,now=100,lease_seconds=10)
        checkpoint(store.conn,first,{},state='queued',phase='financial_analysis',now=101)
        for now in (110,121,132,143,154,165,176,187,198):
            resumed=claim(store.conn,now=now,lease_seconds=10)
            assert resumed['phase']=='financial_analysis'
        assert claim(store.conn,now=209) is None
        job=list_jobs(store.conn,event.tenant_id,event.workspace_id)[0]
        assert (job['attempt'],job['phase_attempt'],job['state'])==(10,9,'failed')


def test_legacy_job_migrates_without_gaining_new_phase_budget(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        store.conn.execute('DROP TABLE room_jobs')
        store.conn.execute("""CREATE TABLE room_jobs (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
            actor_id TEXT NOT NULL, work_key TEXT NOT NULL UNIQUE, input_revision TEXT NOT NULL,
            state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
            lease_token TEXT, lease_until REAL, checkpoint TEXT NOT NULL DEFAULT '{}',
            error TEXT, created REAL NOT NULL)""")
        store.conn.execute("""INSERT INTO room_jobs
            (id,tenant_id,workspace_id,actor_id,work_key,input_revision,state,attempt,created)
            VALUES (?,?,?,?,?,?,'queued',2,?)""",
            ('old',event.tenant_id,event.workspace_id,event.actor_id,event.idempotency_key(),event.input_revision,1))
        store.conn.commit()
        old=claim(store.conn)
        assert (old['phase'],old['attempt'])==('legacy',3)
        with pytest.raises(ValueError,match='three bounded passes'):
            checkpoint(store.conn,old,{},state='queued')
        with pytest.raises(ValueError,match='phase cannot advance'):
            checkpoint(store.conn,old,{},state='queued',phase='draft')
        checkpoint(store.conn,old,{},state='completed')
        assert enqueue(store.conn,event)['phase']=='legacy'


def test_existing_combined_analysis_job_keeps_its_three_pass_budget(tmp_path):
    db=tmp_path/'jobs.db';event=setup(db)
    with Store(db) as store:
        job=enqueue(store.conn,event)
        store.conn.execute("UPDATE room_jobs SET phase='analysis' WHERE id=?",(job['id'],))
        store.conn.commit()
        for attempt in range(1,4):
            running=claim(store.conn)
            assert (running['phase'],running['phase_attempt'])==('analysis',attempt)
            if attempt<3:
                checkpoint(store.conn,running,{},state='queued')
            else:
                with pytest.raises(ValueError,match='in order'):
                    checkpoint(store.conn,running,{},state='queued',phase='review')
                checkpoint(store.conn,running,{},state='queued',phase='render')
        assert claim(store.conn)['phase']=='render'


def test_content_review_is_a_separate_three_pass_phase():
    from delivery.jobs import _next_phase
    job = {'phase': 'review', 'phase_attempt': 14, 'checkpoint': {}}
    assert _next_phase(job, 'content_review') == ('content_review', 0)
    content = {**job, 'phase': 'content_review', 'phase_attempt': 1}
    assert _phase_cap(content) == 3
    assert _next_phase(content, 'material_draft') == ('material_draft', 0)


def test_full_memo_content_cap_covers_new_sections_without_expanding_old_flow():
    for workflow in ('room-v37-isolated-source-unit-content-gate', 'room-v38-full-memo-content-gate',
                     'room-v39-checkpointed-full-memo-gate', 'room-v40-native-claim-full-memo-gate', 'room-v41-structured-section-full-memo-gate', 'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector'):
        assert _phase_cap({'phase': 'content_review', 'checkpoint': {'workflow_contract': workflow}}) == (
            15 if workflow in {'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector'} else
            11 if workflow in {'room-v39-checkpointed-full-memo-gate', 'room-v40-native-claim-full-memo-gate', 'room-v41-structured-section-full-memo-gate'} else
            5 if workflow == 'room-v38-full-memo-content-gate' else 3)


@pytest.mark.parametrize('workflow,cap', [
    ('room-v57-full-relation-material-review', 15),
    ('room-v58-complete-source-concise-memo', 22),
    ('room-v59-sharded-source-adjudication', 26),
    ('room-v60-blind-group-source-assessment', 26),
    ('room-v61-supported-topic-groups', 26),
    ('room-v62-explicit-topic-status', 21),
])
def test_source_checkpoint_cap_matches_expired_lease_recovery(tmp_path, workflow, cap):
    db = tmp_path / 'jobs.db'
    event = setup(db).model_copy(update={'workflow_version': workflow})
    assert _phase_cap({'phase': 'content_review', 'checkpoint': {
        'workflow_contract': workflow}}) == cap
    with Store(db) as store:
        queued = enqueue(store.conn, event)
        store.conn.execute("UPDATE room_jobs SET phase='content_review' WHERE id=?", (queued['id'],))
        store.conn.commit()
        for index in range(cap):
            running = claim(store.conn, now=100 + index * 11, lease_seconds=10)
            assert running['phase_attempt'] == index + 1
            assert running['checkpoint']['workflow_contract'] == workflow
        assert claim(store.conn, now=100 + cap * 11) is None
        final = list_jobs(store.conn, event.tenant_id, event.workspace_id)[0]
        assert (final['state'], final['phase_attempt']) == ('failed', cap)


def test_latest_room_material_contract_cannot_downgrade(tmp_path):
    event = setup(tmp_path / 'jobs.db').model_copy(update={'workflow_version': 'room-v48-narrative-function-review'})
    with Store(tmp_path / 'jobs.db') as store:
        enqueue(store.conn, event)
        running = claim(store.conn, now=100, lease_seconds=20)
        with pytest.raises(ValueError, match='cannot downgrade'):
            checkpoint(store.conn, running, {'material_draft_contract': 'purpose_v11'}, now=101)
        checkpoint(store.conn, running, {'material_draft_contract': 'purpose_v14'}, now=101)
    assert _phase_cap({'phase': 'material_draft', 'checkpoint': {'material_draft_contract': 'purpose_v14'}}) == _phase_cap(
        {'phase': 'material_draft', 'checkpoint': {'material_draft_contract': 'purpose_v13'}})


def test_temporal_material_contract_pair_is_immutable(tmp_path):
    event = setup(tmp_path/'jobs.db').model_copy(update={'workflow_version':'room-v51-temporal-material-scope'})
    with Store(tmp_path/'jobs.db') as store:
        enqueue(store.conn,event)
        running=claim(store.conn,now=100,lease_seconds=20)
        for changed in ({'material_draft_contract':'purpose_v15'},{'material_review_contract':'semantic_v14'}):
            with pytest.raises(ValueError,match='purpose_v16/semantic_v15'):
                checkpoint(store.conn,running,changed,now=101)
        checkpoint(store.conn,running,{'material_draft_contract':'purpose_v16','material_review_contract':'semantic_v15'},now=101)
    assert _phase_cap({'phase':'material_draft','checkpoint':{'material_draft_contract':'purpose_v16'}})==15
    assert _phase_cap({'phase':'material_review','checkpoint':{'material_review_contract':'semantic_v15'}})==15


def test_attributed_period_contract_pair_is_immutable(tmp_path):
    event=setup(tmp_path/'jobs.db').model_copy(update={'workflow_version':'room-v53-attributed-period-selector'})
    with Store(tmp_path/'jobs.db') as store:
        enqueue(store.conn,event);running=claim(store.conn,now=100,lease_seconds=20)
        for changed in ({'material_draft_contract':'purpose_v16'},{'material_review_contract':'semantic_v15'}):
            with pytest.raises(ValueError,match='purpose_v17/semantic_v16'):
                checkpoint(store.conn,running,changed,now=101)
        checkpoint(store.conn,running,{'material_draft_contract':'purpose_v17','material_review_contract':'semantic_v16'},now=101)
    assert _phase_cap({'phase':'material_draft','checkpoint':{'material_draft_contract':'purpose_v17'}})==15
    assert _phase_cap({'phase':'material_review','checkpoint':{'material_review_contract':'semantic_v16'}})==15


def test_typed_temporal_contract_pair_is_immutable(tmp_path):
    event=setup(tmp_path/'jobs.db').model_copy(update={'workflow_version':'room-v54-typed-temporal-selector'})
    with Store(tmp_path/'jobs.db') as store:
        enqueue(store.conn,event);running=claim(store.conn,now=100,lease_seconds=20)
        for changed in ({'material_draft_contract':'purpose_v17'},{'material_review_contract':'semantic_v16'}):
            with pytest.raises(ValueError,match='purpose_v18/semantic_v17'):
                checkpoint(store.conn,running,changed,now=101)
        checkpoint(store.conn,running,{'material_draft_contract':'purpose_v18','material_review_contract':'semantic_v17'},now=101)
    assert _phase_cap({'phase':'content_review','checkpoint':{'workflow_contract':'room-v54-typed-temporal-selector'}})==15
    assert _phase_cap({'phase':'material_draft','checkpoint':{'material_draft_contract':'purpose_v18'}})==15
    assert _phase_cap({'phase':'material_review','checkpoint':{'material_review_contract':'semantic_v17'}})==15


def test_compact_review_contract_pair_is_immutable(tmp_path):
    event=setup(tmp_path/'jobs.db').model_copy(update={'workflow_version':'room-v55-compact-material-review'})
    with Store(tmp_path/'jobs.db') as store:
        enqueue(store.conn,event);running=claim(store.conn,now=100,lease_seconds=20)
        for changed in ({'material_draft_contract':'purpose_v17'},{'material_review_contract':'semantic_v17'}):
            with pytest.raises(ValueError,match='purpose_v18/semantic_v18'):
                checkpoint(store.conn,running,changed,now=101)
        checkpoint(store.conn,running,{'material_draft_contract':'purpose_v18','material_review_contract':'semantic_v18'},now=101)
    assert _phase_cap({'phase':'content_review','checkpoint':{'workflow_contract':'room-v55-compact-material-review'}})==15
    assert _phase_cap({'phase':'material_review','checkpoint':{'material_review_contract':'semantic_v18'}})==15


def test_inline_review_contract_pair_is_immutable(tmp_path):
    event=setup(tmp_path/'jobs.db').model_copy(update={'workflow_version':'room-v56-inline-material-provenance'})
    with Store(tmp_path/'jobs.db') as store:
        enqueue(store.conn,event);running=claim(store.conn,now=100,lease_seconds=20)
        with pytest.raises(ValueError,match='purpose_v18/semantic_v19'):
            checkpoint(store.conn,running,{'material_review_contract':'semantic_v18'},now=101)
        checkpoint(store.conn,running,{'material_draft_contract':'purpose_v18','material_review_contract':'semantic_v19'},now=101)
    assert _phase_cap({'phase':'content_review','checkpoint':{'workflow_contract':'room-v56-inline-material-provenance'}})==15
    assert _phase_cap({'phase':'material_review','checkpoint':{'material_review_contract':'semantic_v19'}})==15


def test_full_relation_review_contract_pair_is_immutable(tmp_path):
    event=setup(tmp_path/'jobs.db').model_copy(update={'workflow_version':'room-v57-full-relation-material-review'})
    with Store(tmp_path/'jobs.db') as store:
        enqueue(store.conn,event);running=claim(store.conn,now=100,lease_seconds=20)
        with pytest.raises(ValueError,match='purpose_v18/semantic_v20'):
            checkpoint(store.conn,running,{'material_review_contract':'semantic_v19'},now=101)
        checkpoint(store.conn,running,{'material_draft_contract':'purpose_v18','material_review_contract':'semantic_v20'},now=101)
    assert _phase_cap({'phase':'content_review','checkpoint':{'workflow_contract':'room-v57-full-relation-material-review'}})==15
    assert _phase_cap({'phase':'material_review','checkpoint':{'material_review_contract':'semantic_v20'}})==15


def test_complete_coverage_checkpoints_have_no_retry_or_contract_downgrade(tmp_path):
    version = 'room-v58-complete-source-concise-memo'
    event = setup(tmp_path / 'jobs.db').model_copy(update={'workflow_version': version})
    with Store(tmp_path / 'jobs.db') as store:
        job = enqueue(store.conn, event)
        assert job['checkpoint']['workflow_contract'] == version
        store.conn.execute("UPDATE room_jobs SET phase='content_review',phase_attempt=21 WHERE id=?", (job['id'],))
        store.conn.commit()
        last = claim(store.conn, now=100, lease_seconds=10)
        assert last['phase_attempt'] == 22
        for changed in ({'material_draft_contract': 'purpose_v17'}, {'material_review_contract': 'semantic_v19'}):
            with pytest.raises(ValueError, match='requires purpose_v18/semantic_v20'):
                checkpoint(store.conn, last, changed, state='queued', phase='material_draft', now=101)
        assert claim(store.conn, now=111) is None
        assert list_jobs(store.conn, event.tenant_id, event.workspace_id)[0]['state'] == 'failed'
    assert _phase_cap({'phase': 'content_review', 'checkpoint': {'workflow_contract': version}}) == 22
    assert _phase_cap({'phase': 'content_review', 'checkpoint': {'workflow_contract': 'room-v57-full-relation-material-review'}}) == 15


def test_public_job_retains_safe_financial_overview_without_private_index_paths():
    from delivery.jobs import public_job
    original = {'id': 'job', 'actor_id': 'actor', 'lease_token': 'secret', 'work_key': 'private',
        'checkpoint': {'workflow_contract': 'room-v63-source-quotes',
            'financial_evidence': {'state': 'indexed_source_only', 'workbook_count': 1,
                'retained_cell_count': 12, 'packet_count': 3, 'semantic_coverage': 'unassessed',
                'financial_validation': 'not_established'},
            'financial_evidence_indexes': {'documents': {'doc': {'manifest_path': '/private/original-sidecar'}}}}}
    public = public_job(original)
    assert 'financial_evidence_indexes' not in public['checkpoint']
    assert '/private/original-sidecar' not in json.dumps(public)
    assert public['checkpoint']['financial_evidence']['retained_cell_count'] == 12
    assert original['checkpoint']['financial_evidence_indexes']['documents']['doc']['manifest_path'] == '/private/original-sidecar'
    assert _phase_cap({'phase': 'content_review', 'checkpoint': {'workflow_contract': 'room-v63-source-quotes'}}) == 21
