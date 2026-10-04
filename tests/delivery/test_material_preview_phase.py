"""Private pre-review material previews from frozen synthetic model sections."""
import json
import os

from delivery import jobs, worker
from delivery.artifacts import get_artifact
from delivery.contracts import REQUIRED_MATERIAL_KINDS
from delivery.release import load_package
from delivery.worker import process_one
from store import Store
from tests.api.test_authentication import secured, sign_in
from tests.api.test_room_financial_phase import room_job


def test_preview_phase_freezes_six_private_pairs_before_semantic_review(
        secured, monkeypatch, tmp_path):
    from delivery import material_stage
    from delivery import investment_memo_stage
    from scripts import private_document_worker

    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(tmp_path / 'private-artifacts'))
    client, db, room_id, job_id = room_job(secured, monkeypatch, tmp_path)
    tenant = secured[2][0][1]
    with Store(db) as store:
        job = jobs.record(store.conn.execute(f'SELECT {jobs.SELECT_COLUMNS} '
            'FROM room_jobs WHERE id=?', (job_id,)).fetchone())
        room = store.get_workspace(tenant, workspace_id=room_id)
        lead = store.get_lead(tenant, room.lead_id)
        sources, _ = investment_memo_stage.room_sources(store, lead, room,
                                                         full_inventory=True)
        source_hash = investment_memo_stage.source_fingerprint(job, lead, sources)
        memo = {'state': 'accepted', 'source_hash': source_hash,
                'recommendation': 'defer_pending_evidence',
                'sections': [['Summary', 'The synthetic source reports one pilot [S1].',
                              '[S1] Synthetic source']]}
        material = {'state': 'accepted', 'source_hash': source_hash,
                    'decks': {'intro_deck': {'sections': [[
                        'Product report', 'The synthetic source reports one pilot [S1].',
                        '[S1] Synthetic source', 'evidence']]},
                        'pitch_deck': {'sections': [[
                        'Open question', 'The source does not establish revenue [S1].',
                        '[S1] Synthetic source', 'statement']]}}}
        checkpoint = {'investment_memo': memo, 'materials': material,
                      'memo_source_hash': source_hash,
                      'financial_model': {'state': 'awaiting_input'}}
        store.conn.execute("UPDATE room_jobs SET phase='material_preview',checkpoint=? "
                           'WHERE id=?', (json.dumps(checkpoint), job_id))
        store.conn.commit()

    replay_calls = []
    def accepted_only(frozen_job, frozen_memo, frozen_material):
        replay_calls.append(frozen_job['input_revision'])
        assert frozen_memo == memo and frozen_material == material
        return frozen_material
    monkeypatch.setattr(material_stage, 'validate_material_checkpoint', accepted_only)

    render_calls = []
    def synthetic_renderer(command, root, **kwargs):
        render_calls.append(root)
        old = os.getcwd()
        try:
            os.chdir(root)
            private_document_worker.main()
        finally:
            os.chdir(old)
    monkeypatch.setattr(worker, 'run_private', synthetic_renderer)

    assert process_one(db) == job_id
    with Store(db) as store:
        row = jobs.record(store.conn.execute(f'SELECT {jobs.SELECT_COLUMNS} '
            'FROM room_jobs WHERE id=?', (job_id,)).fetchone())
        assert row['phase'] == 'material_review' and row['state'] == 'queued', (
            row['phase'], row['state'], row['error'])
        preview = row['checkpoint']['material_preview']
        assert preview['state'] == 'accepted' and preview['input_revision'] == job['input_revision']
        assert len(preview['artifact_ids']) == 6
        assert 'material_review' not in row['checkpoint']
        kinds = [get_artifact(store.conn, tenant, artifact_id)['kind']
                 for artifact_id in preview['artifact_ids']]
        assert kinds == [kind for _, kind, _ in worker.PREVIEW_FILES]
        assert all(get_artifact(store.conn, tenant, artifact_id)['state'] == 'draft'
                   for artifact_id in preview['artifact_ids'])
        first_id = preview['artifact_ids'][0]
        response = client.get(f'/api/rooms/{room_id}/artifacts/{first_id}/preview')
        assert response.status_code == 200 and response.content.startswith(b'PK')
        sign_in(client, secured[2][1])
        assert client.get(f'/api/rooms/{room_id}/artifacts/{first_id}/preview').status_code == 404
        sign_in(client, secured[2][0])
        validation = client.post(f'/api/rooms/{room_id}/validate')
        assert validation.status_code == 200
        assert validation.json()['eligible_for_release'] is False
        assert 'missing_file:investment_memorandum:pdf' in validation.json()['blockers']
        manifest, _, _, _ = load_package(store, tenant, validation.json()['package_id'])
        assert manifest.requested == REQUIRED_MATERIAL_KINDS and manifest.files == ()
        # A retried phase reuses the frozen Office/PDF bytes and occupied slots.
        store.conn.execute("UPDATE room_jobs SET phase='material_preview',state='queued',"
                           'phase_attempt=0,lease_token=NULL,lease_until=NULL WHERE id=?',
                           (job_id,))
        store.conn.commit()
    assert process_one(db) == job_id
    with Store(db) as store:
        replayed = jobs.record(store.conn.execute(f'SELECT {jobs.SELECT_COLUMNS} '
            'FROM room_jobs WHERE id=?', (job_id,)).fetchone())
        assert replayed['phase'] == 'material_review'
        assert replayed['checkpoint']['material_preview']['artifact_ids'] == preview['artifact_ids']
        assert store.conn.execute("SELECT count(*) FROM room_artifacts WHERE tenant_id=? "
                                  "AND workspace_id=?", (tenant, room_id)).fetchone()[0] == 6
    assert len(render_calls) == 1 and len(replay_calls) == 2
