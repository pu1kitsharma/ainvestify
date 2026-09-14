"""Stable local research API. Restart after backend edits; no reload mid-job."""
import argparse
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("api.main:app", host="127.0.0.1", port=args.port, timeout_graceful_shutdown=5)
