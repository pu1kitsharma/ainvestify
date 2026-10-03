"""Opaque revocable sessions; legacy tenants are never claimed at signup."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS auth_identities (
 issuer TEXT NOT NULL, subject TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY(issuer, subject));
CREATE TABLE IF NOT EXISTS auth_sandboxes (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS auth_memberships (
 tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(tenant_id,user_id));
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
 csrf TEXT NOT NULL, created REAL NOT NULL, touched REAL NOT NULL, expires REAL NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS auth_flows (
 state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, nonce TEXT NOT NULL,
 verifier TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS auth_local_credentials (
 user_id TEXT PRIMARY KEY REFERENCES auth_users(id), login_id TEXT NOT NULL UNIQUE,
 salt BLOB NOT NULL, verifier BLOB NOT NULL, failed_attempts INTEGER NOT NULL DEFAULT 0,
 locked_until REAL NOT NULL DEFAULT 0);
"""
COOKIE, FLOW_COOKIE = "deal_session", "deal_login"
IDLE_SECONDS, ABSOLUTE_SECONDS = 1800, 28800


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _csrf_for_token(token):
    return hmac.new(token.encode(), b"deal-session-csrf-v1", hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Identity:
    user_id: str
    tenant_id: str
    role: str
    csrf: str


def provision_verified_identity(conn, issuer: str, subject: str):
    """Only after ID-token verification; never accept client-submitted claims."""
    if not issuer or not subject:
        raise ValueError("Verified issuer and subject required")
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute("SELECT user_id FROM auth_identities WHERE issuer=? AND subject=?",
            (issuer, subject)).fetchone()
        if existing:
            user = existing[0]
            sandbox = conn.execute("SELECT id FROM auth_sandboxes WHERE owner_id=?", (user,)).fetchone()
            if not sandbox:
                raise ValueError("Account sandbox unavailable")
            tenant = sandbox[0]
        else:
            user, tenant = "user_" + secrets.token_hex(16), "sandbox_" + secrets.token_hex(16)
            conn.execute("INSERT INTO auth_users(id) VALUES (?)", (user,))
            conn.execute("INSERT INTO auth_identities VALUES (?,?,?)", (issuer, subject, user))
            conn.execute("INSERT INTO auth_sandboxes VALUES (?,?)", (tenant, user))
            conn.execute("INSERT INTO auth_memberships VALUES (?,?,?,1)", (tenant, user, "owner"))
        conn.commit()
        return user, tenant
    except Exception:
        conn.rollback()
        raise


def has_access(conn, user, tenant):
    return conn.execute("""SELECT m.role FROM auth_memberships m JOIN auth_users u ON u.id=m.user_id
        WHERE m.user_id=? AND m.tenant_id=? AND m.active=1 AND u.disabled=0""", (user, tenant)).fetchone()


def create_session(conn, user, tenant, *, now=None):
    if not has_access(conn, user, tenant):
        raise ValueError("Account access unavailable")
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    csrf = _csrf_for_token(token)
    conn.execute("INSERT INTO auth_sessions VALUES (?,?,?,?,?,?,?,0)",
        (token_hash(token), user, tenant, token_hash(csrf), now, now, now + ABSOLUTE_SECONDS))
    conn.commit()
    return token, csrf


def resolve_session(conn, token, *, now=None):
    if not token or len(token) > 256:
        return None
    now = time.time() if now is None else now
    row = conn.execute("""SELECT s.user_id,s.tenant_id,m.role,s.csrf FROM auth_sessions s
        JOIN auth_users u ON u.id=s.user_id
        JOIN auth_memberships m ON m.user_id=s.user_id AND m.tenant_id=s.tenant_id
        WHERE s.token_hash=? AND s.revoked=0 AND s.expires>? AND s.touched>?
        AND u.disabled=0 AND m.active=1""", (token_hash(token), now, now-IDLE_SECONDS)).fetchone()
    if not row:
        return None
    csrf = _csrf_for_token(token)
    if not secrets.compare_digest(row[3], token_hash(csrf)):
        return None
    conn.execute("UPDATE auth_sessions SET touched=? WHERE token_hash=?", (now, token_hash(token)))
    conn.commit()
    return Identity(row[0], row[1], row[2], csrf)


def revoke_session(conn, token):
    conn.execute("UPDATE auth_sessions SET revoked=1 WHERE token_hash=?", (token_hash(token or ""),))
    conn.commit()


def start_flow(conn):
    state, browser, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(4))
    conn.execute("DELETE FROM auth_flows WHERE expires<?", (time.time(),))
    conn.execute("INSERT INTO auth_flows VALUES (?,?,?,?,?)",
        (token_hash(state), token_hash(browser), nonce, verifier, time.time()+600))
    conn.commit()
    return state, browser, nonce, verifier


def consume_flow(conn, state, browser):
    if not state or not browser or len(state) > 256 or len(browser) > 256:
        raise ValueError("Invalid login callback")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT browser_hash,nonce,verifier,expires FROM auth_flows WHERE state_hash=?",
            (token_hash(state),)).fetchone()
        if not row or row[3] <= time.time() or not secrets.compare_digest(row[0], token_hash(browser)):
            raise ValueError("Invalid login callback")
        conn.execute("DELETE FROM auth_flows WHERE state_hash=?", (token_hash(state),))
        conn.commit()
        return row[1], row[2]
    except Exception:
        conn.rollback()
        raise
