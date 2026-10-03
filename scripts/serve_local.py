"""Stable local research API. Restart after backend edits; no reload mid-job."""
import argparse
import os
import sys
import subprocess
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--without-worker",action="store_true",help="Run API only; use a separately supervised room worker")
    parser.add_argument("--local-dev",action="store_true",help="Explicit loopback HTTP frontend origin for local development only")
    args = parser.parse_args()
    if args.local_dev:
        if os.environ.get("APP_ENV", "development") != "development":
            parser.error("--local-dev requires APP_ENV=development")
        origin = "http://127.0.0.1:5173"
        if os.environ.get("APP_ORIGIN", origin) != origin:
            parser.error("--local-dev requires APP_ORIGIN=" + origin)
        os.environ.update(APP_ENV="development", ALLOW_LOOPBACK_HTTP="1", APP_ORIGIN=origin,
                          LOCAL_DEV_PASSWORD_LOGIN="1")
    # Callback query strings contain one-time authorization codes. Never put
    # them into Uvicorn access logs.
    worker=None if args.without_worker else subprocess.Popen([sys.executable,
        str(Path(__file__).resolve().parent/'run_room_worker.py'),'--watch'])
    try:
        uvicorn.run("api.main:app", host="127.0.0.1", port=args.port, timeout_graceful_shutdown=5, access_log=False)
    finally:
        if worker:
            worker.terminate()  # Cooperative stop: finish the active bounded pass.
            worker.wait(timeout=130)
