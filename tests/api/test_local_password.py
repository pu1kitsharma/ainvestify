import hashlib
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.deps import get_store
from api.main import app
from api.routers.auth import _loopback_client
from security.identity import COOKIE
from security.local_password import authenticate, create_user, enabled
from store import Store


@pytest.fixture
def local_login(tmp_path, monkeypatch):
    monkeypatch.setattr('api.routers.auth._loopback_client',lambda request: True)
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('APP_ORIGIN','http://127.0.0.1:5173')
    monkeypatch.setenv('ALLOW_LOOPBACK_HTTP','1')
    monkeypatch.setenv('LOCAL_DEV_PASSWORD_LOGIN','1')
    db=tmp_path/'users.sqlite'
    with Store(db) as store:
        user,tenant=create_user(store.conn,'temporary','synthetic-long-password-123456')
    def override():
        with Store(db) as store:yield store
    app.dependency_overrides[get_store]=override
    yield TestClient(app,base_url='http://127.0.0.1:5173'),db,user,tenant
    app.dependency_overrides.clear()


def test_temp_login_creates_session_with_only_hashes_in_database(local_login):
    client,db,user,tenant=local_login
    response=client.post('/api/auth/local-login',json={'user_id':'temporary','password':'synthetic-long-password-123456'},
                         headers={'origin':'http://127.0.0.1:5173'})
    assert response.status_code==200
    assert response.cookies.get(COOKIE)
    me=client.get('/api/auth/me').json()
    assert me['tenant_id']==tenant
    assert me['display_name']=='temporary' and me['sign_in_method']=='local'
    with Store(db) as store:
        salt,verifier=store.conn.execute('SELECT salt,verifier FROM auth_local_credentials WHERE user_id=?',(user,)).fetchone()
        assert verifier!=b'synthetic-long-password-123456' and len(salt)==16
        token_hash,csrf_hash=store.conn.execute('SELECT token_hash,csrf FROM auth_sessions WHERE user_id=?',(user,)).fetchone()
        assert token_hash==hashlib.sha256(response.cookies[COOKIE].encode()).hexdigest()
        assert csrf_hash==hashlib.sha256(me['csrf_token'].encode()).hexdigest()
        assert me['csrf_token'] not in db.read_bytes().decode('latin1')
        assert response.cookies[COOKIE] not in db.read_bytes().decode('latin1')
        assert b'synthetic-long-password-123456' not in db.read_bytes()


def test_origin_restriction_and_lockout(local_login):
    client,db,_,_=local_login
    body={'user_id':'temporary','password':'synthetic-long-password-123456'}
    assert client.post('/api/auth/local-login',json=body).status_code==403
    assert client.post('/api/auth/local-login',json=body,headers={'origin':'https://evil.example'}).status_code==403
    for _ in range(5):
        assert client.post('/api/auth/local-login',json={**body,'password':'wrong'},
                           headers={'origin':'http://127.0.0.1:5173'}).status_code==401
    assert client.post('/api/auth/local-login',json=body,
                       headers={'origin':'http://127.0.0.1:5173'}).status_code==401
    with Store(db) as store:
        assert authenticate(store.conn,'temporary',body['password'],now=time.time()+301) is not None


def test_both_loopback_origins_can_login_and_write(local_login):
    client,_,_,_=local_login
    body={'user_id':'temporary','password':'synthetic-long-password-123456'}
    response=client.post('/api/auth/local-login',json=body,
                         headers={'origin':'http://localhost:5173'})
    assert response.status_code==200
    csrf=client.get('/api/auth/me').json()['csrf_token']
    created=client.post('/api/deals',json={'name':'Synthetic local test'},
                        headers={'origin':'http://localhost:5173','x-csrf-token':csrf})
    assert created.status_code==200
    assert client.post('/api/deals',json={'name':'Blocked'},
                       headers={'origin':'http://attacker.example','x-csrf-token':csrf}).status_code==403


def test_production_disables_temporary_login(local_login,monkeypatch):
    client,db,_,_=local_login
    assert enabled()
    monkeypatch.setenv('APP_ENV','production')
    assert not enabled()
    assert client.get('/api/auth/config').json()['local_password_enabled'] is False
    assert client.post('/api/auth/local-login',json={'user_id':'temporary','password':'synthetic-long-password-123456'},
                       headers={'origin':'http://127.0.0.1:5173'}).status_code==404
    with Store(db) as store:
        with pytest.raises(PermissionError):authenticate(store.conn,'temporary','synthetic-long-password-123456')


def test_client_host_must_be_loopback():
    assert _loopback_client(SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')))
    assert not _loopback_client(SimpleNamespace(client=SimpleNamespace(host='192.0.2.1')))
