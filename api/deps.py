"""Request-scoped persistence and server-derived sandbox/reviewer identity."""
from __future__ import annotations
import secrets
import os
from fastapi import Depends, HTTPException, Request
from security.identity import COOKIE, resolve_session
from security.oidc import app_origin
from store import DEFAULT_DB_PATH, Store


def get_store():
    with Store(DEFAULT_DB_PATH) as store:
        yield store


def valid_request_origin(value: str | None) -> bool:
    """Accept both loopback spellings only in the explicit local dev runtime."""
    origin = app_origin()
    if value == origin:
        return True
    return bool(os.environ.get("APP_ENV") == "development"
        and os.environ.get("ALLOW_LOOPBACK_HTTP") == "1"
        and origin == "http://127.0.0.1:5173"
        and value == "http://localhost:5173")


def get_identity(request: Request, store=Depends(get_store)):
    identity = resolve_session(store.conn, request.cookies.get(COOKIE))
    if identity is None:
        raise HTTPException(401, "Sign in to access your private sandbox.")
    store.authenticated_identity = identity
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        try:
            valid_origin = valid_request_origin(request.headers.get("origin"))
        except ValueError:
            raise HTTPException(503, "Application origin is not configured securely.")
        if (not valid_origin
                or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), identity.csrf)):
            raise HTTPException(403, "Request origin or CSRF token is invalid.")
    return identity


def get_tenant_id(identity=Depends(get_identity)) -> str:
    return identity.tenant_id


def get_reviewer(identity=Depends(get_identity)) -> str:
    return identity.user_id
