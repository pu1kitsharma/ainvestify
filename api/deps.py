"""
Shared FastAPI dependencies.

`sqlite3.Connection` isn't safe to share across threads the way the CLI's
one long-lived process assumes (plan §2) -- so unlike the CLI, which opens
one Store for its whole run, the API opens and closes one Store per
request via Store's existing __enter__/__exit__.
"""
from typing import Optional

from fastapi import Header

from store import DEFAULT_DB_PATH, Store

# Phase 0 is single-user (same convention main.py already uses) -- multi-
# tenancy is designed for (every store method is tenant-scoped) but there's
# no real auth yet, so this header is accepted for forward-compatibility
# and defaults to the same tenant the CLI writes under.
DEFAULT_TENANT_ID = "default_tenant"


def get_store():
    with Store(DEFAULT_DB_PATH) as store:
        yield store


def get_tenant_id(x_tenant_id: Optional[str] = Header(default=None)) -> str:
    return x_tenant_id or DEFAULT_TENANT_ID


# No real auth yet (plan §6 explicitly scopes that out for this phase) --
# this identifies who a decision's audit trail should be attributed to,
# the same role main.py's hardcoded `reviewer = "cli_user"` plays for the CLI.
DEFAULT_REVIEWER = "api_user"


def get_reviewer(x_reviewer: Optional[str] = Header(default=None)) -> str:
    return x_reviewer or DEFAULT_REVIEWER
