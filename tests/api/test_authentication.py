from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.deps import get_store
from security.identity import (COOKIE, create_session, provision_verified_identity,
    start_flow, consume_flow, resolve_session, revoke_session)
from store import Store


@pytest.fixture
def secured(tmp_path, monkeypatch):
    app.dependency_overrides.clear()
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    # Actual session/CSRF dependencies run; only config and DB are isolated.
    monkeypatch.setattr("api.deps.app_origin", lambda: "http://testserver")
    db = tmp_path / "isolated.db"
    with Store(db) as store:
        users = []
        for subject in ("alice", "bob"):
            user, tenant = provision_verified_identity(store.conn,"https://accounts.google.com",subject)
            token, csrf = create_session(store.conn,user,tenant)
            users.append((user,tenant,token,csrf))
    def override():
        with Store(db) as store:
            yield store
    app.dependency_overrides[get_store] = override
    yield TestClient(app), db, users
    app.dependency_overrides.clear()


def sign_in(client, user):
    client.cookies.set(COOKIE,user[2])
    client.headers.update({"origin":"http://testserver", "x-csrf-token":user[3]})


def test_anonymous_headers_never_authenticate(secured):
    client, _, _ = secured
    for path in ("/api/deals", "/api/leads", "/api/operations/workspaces", "/api/operations/public-research-status"):
        assert client.get(path, headers={"X-Tenant-ID":"default_tenant", "X-Reviewer":"admin"}).status_code == 401
    assert client.get("/memo_output/anything.png").status_code == 404


def test_two_users_cannot_access_each_other_even_with_headers(secured):
    client, _, users = secured
    sign_in(client,users[0])
    response = client.post("/api/deals",json={"name":"Private synthetic company"})
    assert response.status_code == 200
    deal_id = response.json()["id"]
    sign_in(client,users[1])
    response = client.get(f"/api/deals/{deal_id}",headers={"X-Tenant-ID":users[0][1]})
    assert response.status_code == 404
    assert client.get("/api/deals").json() == []


def test_csrf_logout_and_revocation(secured):
    client, db, users = secured
    sign_in(client,users[0])
    assert client.post("/api/deals",json={"name":"test"},headers={"origin":"https://evil.example"}).status_code == 403
    assert client.post("/api/deals",json={"name":"test"},headers={"x-csrf-token":""}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set(COOKIE,users[0][2])
    assert client.get("/api/auth/me").status_code == 401
    sign_in(client,users[1])
    with Store(db) as store:
        store.conn.execute("UPDATE auth_memberships SET active=0 WHERE user_id=?",(users[1][0],))
        store.conn.commit()
    assert client.get("/api/deals").status_code == 401


def test_concurrent_signup_and_legacy_quarantine(secured):
    _, db, _ = secured
    def signup(_):
        with Store(db) as store:
            return provision_verified_identity(store.conn,"https://accounts.google.com","same-subject")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(signup,range(4)))
    assert len(set(results)) == 1
    assert results[0][1] != "default_tenant"
    with Store(db) as store:
        other = provision_verified_identity(store.conn,"https://other.example","same-subject")
    assert other != results[0]


def test_flow_replay_browser_binding_and_expiry(secured):
    _, db, users = secured
    with Store(db) as store:
        state,browser,nonce,verifier = start_flow(store.conn)
        with pytest.raises(ValueError):
            consume_flow(store.conn,state,"wrong-browser")
        assert consume_flow(store.conn,state,browser) == (nonce,verifier)
        with pytest.raises(ValueError):
            consume_flow(store.conn,state,browser)
        token,_ = create_session(store.conn,*users[0][:2],now=100)
        assert resolve_session(store.conn,token,now=1901) is None
