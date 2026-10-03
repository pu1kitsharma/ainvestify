"""Provider tokens stay server-side; browser carries an opaque session cookie."""
import ipaddress
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from api.deps import get_identity, get_store, valid_request_origin
from security.identity import (COOKIE, FLOW_COOKIE, ABSOLUTE_SECONDS, consume_flow,
    create_session, provision_verified_identity, revoke_session, start_flow)
from security.oidc import OIDCConfig, OIDCProvider, app_origin
from security.local_password import authenticate, enabled as local_password_enabled

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def provider():
    try:
        return OIDCProvider(OIDCConfig.load())
    except ValueError:
        raise HTTPException(503, "Sign-in needs Google OAuth client configuration on the server.")


@router.get("/config")
def config():
    try:
        OIDCConfig.load()
        configured = True
    except ValueError:
        configured = False
    return {"configured": configured, "provider": "Google",
            "login_url": app_origin() + "/api/auth/login" if configured else "/api/auth/login",
            "local_password_enabled": local_password_enabled()}


class LocalCredentials(BaseModel):
    user_id: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _loopback_client(request: Request):
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        return False


@router.post("/local-login")
def local_login(credentials: LocalCredentials, request: Request, store=Depends(get_store)):
    if not local_password_enabled():
        raise HTTPException(404, "Temporary sign-in is unavailable.")
    if not _loopback_client(request):
        raise HTTPException(403, "Temporary sign-in requires loopback access.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "JSON request required.")
    if not valid_request_origin(request.headers.get("origin")):
        raise HTTPException(403, "Request origin is invalid.")
    account = authenticate(store.conn, credentials.user_id, credentials.password)
    if account is None:
        raise HTTPException(401, "Invalid user ID or password.")
    revoke_session(store.conn, request.cookies.get(COOKIE))
    token, _ = create_session(store.conn, *account)
    response = JSONResponse({"signed_in": True})
    response.set_cookie(COOKIE, token, max_age=ABSOLUTE_SECONDS, httponly=True,
        secure=app_origin().startswith("https:"), samesite="lax", path="/")
    return response


@router.get("/login")
def login(store=Depends(get_store)):
    oidc = provider()
    state, browser, nonce, verifier = start_flow(store.conn)
    try:
        url = oidc.authorization_url(state, nonce, verifier)
    except Exception:
        raise HTTPException(502, "Sign-in provider unavailable.")
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(FLOW_COOKIE, browser, max_age=600, httponly=True,
        secure=app_origin().startswith("https:"), samesite="lax", path="/api/auth")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "", store=Depends(get_store)):
    oidc = provider()
    try:
        nonce, verifier = consume_flow(store.conn, state, request.cookies.get(FLOW_COOKIE))
        if not code or len(code) > 4096:
            raise ValueError("Invalid callback")
        issuer, subject = oidc.verify_code(code, nonce, verifier)
        user, tenant = provision_verified_identity(store.conn, issuer, subject)
        revoke_session(store.conn, request.cookies.get(COOKIE))
        token, _ = create_session(store.conn, user, tenant)
    except Exception:
        raise HTTPException(400, "Sign-in failed or expired. Start sign-in again.")
    response = RedirectResponse(app_origin() + "/", status_code=303)
    response.set_cookie(COOKIE, token, max_age=ABSOLUTE_SECONDS, httponly=True,
        secure=app_origin().startswith("https:"), samesite="lax", path="/")
    response.delete_cookie(FLOW_COOKIE, path="/api/auth")
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return response


@router.get("/me")
def me(identity=Depends(get_identity), store=Depends(get_store)):
    local = store.conn.execute("SELECT login_id FROM auth_local_credentials WHERE user_id=?",
                               (identity.user_id,)).fetchone()
    display_name = local[0] if local else "Google account"
    return {"user_id": identity.user_id, "tenant_id": identity.tenant_id,
        "role": identity.role, "csrf_token": identity.csrf,
        "display_name": display_name, "sign_in_method": "local" if local else "google"}


@router.post("/logout", status_code=204)
def logout(request: Request, identity=Depends(get_identity), store=Depends(get_store)):
    revoke_session(store.conn, request.cookies.get(COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response
