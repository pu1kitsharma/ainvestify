"""Worker for the phased deal-documents workflow (systemd: investify-deal-documents).

Claims one queued phase at a time from the app database, runs it against
loopback Ollama and records every step for the room UI. A heartbeat thread keeps
the lease alive during long model calls; if the worker dies, the next claim
re-queues the phase and it resumes from its last cached step.
"""
import argparse
import logging
import sqlite3
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery.deal_documents import runs  # noqa: E402
from delivery.deal_documents.pipeline import run_phase  # noqa: E402

log = logging.getLogger('deal-documents-worker')


def connect(db):
    # Pipeline steps may run in a thread pool; the run Tracker serialises their use of this connection.
    conn = sqlite3.connect(db, timeout=30, isolation_level=None, check_same_thread=False)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def beat(db, run_id, token, stop):
    conn = connect(db)
    while not stop.wait(60):
        try:
            runs.heartbeat(conn, run_id, token)
        except sqlite3.Error as exc:
            log.warning('heartbeat failed: %s', exc)
    conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='/home/investify/private/app.db')
    parser.add_argument('--poll', type=float, default=5)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    conn = connect(args.db)
    runs.ensure(conn)
    while True:
        claimed = runs.claim(conn)
        if claimed is None:
            if args.once:
                return
            time.sleep(args.poll)
            continue
        run, phase, token = claimed
        log.info('run %s: %s phase started', run['id'], phase)
        stop = threading.Event()
        thread = threading.Thread(target=beat, args=(args.db, run['id'], token, stop), daemon=True)
        thread.start()
        try:
            outcome = run_phase(conn, run, phase, token, db_path=args.db)
        finally:
            stop.set()
            thread.join()
        log.info('run %s: %s phase %s', run['id'], phase, outcome)
        if args.once:
            return


if __name__ == '__main__':
    main()
