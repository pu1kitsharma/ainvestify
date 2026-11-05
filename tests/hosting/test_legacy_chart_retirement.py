"""Public API must not resume the retired repo-local financial renderer."""
from api.routers import compilation
from tests.api.test_authentication import secured, sign_in  # noqa: F401


def test_legacy_renderer_cannot_write_and_other_tenant_still_gets_404(secured, monkeypatch):
    client, _, users = secured
    sign_in(client, users[0])
    deal = client.post('/api/deals', json={'name': 'Synthetic private chart case'}).json()
    called = []

    def unsafe_renderer(*args, **kwargs):
        called.append(True)
        raise AssertionError('Retired renderer must not run')

    monkeypatch.setattr(compilation, '_run_rerun_analytics', unsafe_renderer)
    response = client.post(f"/api/deals/{deal['id']}/analytics/rerun")
    assert response.status_code == 410
    assert 'deal room' in response.json()['detail']
    sign_in(client, users[1])
    assert client.post(f"/api/deals/{deal['id']}/analytics/rerun").status_code == 404
    assert called == []
