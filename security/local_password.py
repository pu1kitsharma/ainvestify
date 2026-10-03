"""Explicit loopback-only temporary password login, excluded from release auth."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time

from security.oidc import app_origin

ITERATIONS = 600_000
MAX_FAILURES = 5
LOCK_SECONDS = 300
LOGIN_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")
_DUMMY_SALT = b"local-login-dummy"


def enabled():
    try:
        return (os.environ.get("LOCAL_DEV_PASSWORD_LOGIN") == "1"
            and os.environ.get("APP_ENV") == "development"
            and os.environ.get("ALLOW_LOOPBACK_HTTP") == "1"
            and app_origin() == "http://127.0.0.1:5173")
    except ValueError:
        return False


def _derive(password: str, salt: bytes):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)


def create_user(conn, login_id: str, password: str):
    if not enabled():
        raise PermissionError("Temporary account creation is disabled")
    if not LOGIN_ID.fullmatch(login_id) or not 16 <= len(password) <= 256:
        raise ValueError("Invalid temporary credentials")
    salt = secrets.token_bytes(16)
    verifier = _derive(password, salt)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM auth_local_credentials WHERE login_id=?", (login_id,)).fetchone():
            raise ValueError("Temporary user ID already exists")
        user, tenant = "user_" + secrets.token_hex(16), "sandbox_" + secrets.token_hex(16)
        conn.execute("INSERT INTO auth_users(id) VALUES (?)", (user,))
        conn.execute("INSERT INTO auth_sandboxes VALUES (?,?)", (tenant, user))
        conn.execute("INSERT INTO auth_memberships VALUES (?,?,?,1)", (tenant, user, "owner"))
        conn.execute("INSERT INTO auth_local_credentials(user_id,login_id,salt,verifier) VALUES (?,?,?,?)",
                     (user, login_id, salt, verifier))
        conn.commit()
        return user, tenant
    except Exception:
        conn.rollback()
        raise


def authenticate(conn, login_id: str, password: str, *, now=None):
    if not enabled():
        raise PermissionError("Temporary sign-in is disabled")
    if not isinstance(login_id, str) or not isinstance(password, str) or len(login_id) > 64 or len(password) > 256:
        return None
    now = time.time() if now is None else now
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("""SELECT c.user_id,c.salt,c.verifier,c.failed_attempts,c.locked_until,s.id
            FROM auth_local_credentials c JOIN auth_sandboxes s ON s.owner_id=c.user_id
            JOIN auth_users u ON u.id=c.user_id WHERE c.login_id=? AND u.disabled=0""", (login_id,)).fetchone()
        salt = row[1] if row else _DUMMY_SALT
        candidate = _derive(password, salt)
        valid = bool(row and row[4] <= now and secrets.compare_digest(candidate, row[2]))
        if valid:
            from security.identity import has_access
            if not has_access(conn, row[0], row[5]):
                valid = False
        if row:
            if valid:
                conn.execute("UPDATE auth_local_credentials SET failed_attempts=0,locked_until=0 WHERE user_id=?", (row[0],))
            elif row[4] <= now:
                failures = row[3] + 1
                conn.execute("UPDATE auth_local_credentials SET failed_attempts=?,locked_until=? WHERE user_id=?",
                             (failures, now + LOCK_SECONDS if failures >= MAX_FAILURES else 0, row[0]))
        conn.commit()
        return (row[0], row[5]) if valid else None
    except Exception:
        conn.rollback()
        raise
