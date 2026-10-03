"""Provision one isolated loopback-only temporary user; print a private credential file path."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from security.local_password import create_user, enabled
from store import DEFAULT_DB_PATH, Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="temporary")
    args = parser.parse_args()
    if not enabled():
        parser.error("Temporary account creation requires explicit loopback development settings")
    password = secrets.token_urlsafe(32)
    directory = Path(tempfile.mkdtemp(prefix="deal-local-credentials-", dir="/private/tmp"))
    path = directory / "login.txt"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(f"User ID: {args.user_id}\nPassword: {password}\n")
        with Store(DEFAULT_DB_PATH) as store:
            create_user(store.conn, args.user_id, password)
    except Exception:
        path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    print(f"Temporary credentials saved at {path} (mode 0600).")


if __name__ == "__main__":
    main()
