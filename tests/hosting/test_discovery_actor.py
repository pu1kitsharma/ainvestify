"""Server-captured discovery actors cannot fall back to legacy preparation."""
import pytest

from api.models import WebSourceRequest
from api.routers import leads, operations, rooms
from agents.analysis.operating_workflow import reconcile_workspace
from schemas import WebSourcingRun
from security.identity import provision_verified_identity
from store import Store
from tests.analysis.test_operating_workflow import company


@pytest.mark.parametrize('revoked', [False, True])
def test_background_actor_survives_store_reopen_and_revocation_is_checked(tmp_path, monkeypatch, revoked):
    db = tmp_path / 'private.db'
    with Store(db) as store:
        actor, tenant = provision_verified_identity(store.conn, 'https://accounts.google.com', 'fixture-owner')
        other, _ = provision_verified_identity(store.conn, 'https://accounts.google.com', 'fixture-other')
        lead = company(store, tenant)
        workspace = reconcile_workspace(store, lead)
        run = WebSourcingRun(tenant_id=tenant, thesis='Synthetic discovery', model='fixture')
        store.save_web_run(run)
    calls = []

    def discover(store, saved_run, **kwargs):
        assert store.authenticated_identity.user_id == actor
        assert kwargs['preliminary_only'] is True
        saved_run.lead_ids = [lead.id]
        saved_run.status = 'completed'
        store.save_web_run(saved_run)
        if revoked:
            store.conn.execute('UPDATE auth_memberships SET active=0 WHERE user_id=?', (actor,))
            store.conn.commit()
        return saved_run

    def activate(store, identity, lead_id):
        assert (identity.user_id, identity.tenant_id, lead_id) == (actor, tenant, lead.id)
        assert identity.user_id != other
        calls.append(identity.user_id)
        return {'workspace_id': workspace.id, 'job': {'id': 'synthetic-durable-job'}}

    def no_legacy(*args, **kwargs):
        pytest.fail('Legacy in-process preparation must not run')

    monkeypatch.setattr(leads, 'source_companies', discover)
    monkeypatch.setattr(rooms, 'activate', activate)
    monkeypatch.setattr(operations, 'make_preparation_model', no_legacy)
    assert leads._web_slot.acquire(blocking=False)
    leads._run_web_job(db, run, WebSourceRequest(thesis=run.thesis, prepare_workflow=True), actor_id=actor)
    with Store(db) as store:
        saved = store.get_web_run(tenant, run.id)
        if revoked:
            assert calls == []
            assert 'automatic_preparation_lead_id' not in saved.generation_config
            assert any('PermissionError' in warning for warning in saved.warnings)
        else:
            assert calls == [actor]
            assert saved.generation_config['automatic_preparation_lead_id'] == lead.id
            assert store.get_workspace(tenant, lead_id=lead.id).automation.worker_id == 'durable-room'


def test_client_actor_fields_cannot_replace_the_server_identity(secured, monkeypatch):
    from tests.api.test_authentication import sign_in
    client, _, users = secured
    sign_in(client, users[0])
    seen = []

    def capture(db_path, run, body, *, actor_id=None):
        seen.append((actor_id, run.tenant_id))
        leads._web_slot.release()

    monkeypatch.setattr(leads, '_run_web_job', capture)
    response = client.post('/api/leads/web-runs', json={
        'thesis': 'Synthetic discovery', 'prepare_workflow': True,
        'actor_id': users[1][0], 'tenant_id': users[1][1],
    })
    assert response.status_code == 202
    assert seen == [(users[0][0], users[0][1])]


from tests.api.test_authentication import secured  # noqa: E402,F401
