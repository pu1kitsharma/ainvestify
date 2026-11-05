"""Run one bounded durable room job. Invoke from an external scheduler, not FastAPI."""
import argparse
import os
from pathlib import Path
import sys
import signal
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path)
    parser.add_argument('--env-file',type=Path,help='Literal server configuration, loaded before application imports')
    parser.add_argument('--watch',action='store_true',help='One external worker; finish current bounded job on termination')
    args=parser.parse_args()
    if args.env_file:
        from scripts.local_hosting import read_env_file
        try:
            os.environ.update(read_env_file(args.env_file))
        except (OSError,ValueError):
            parser.error('Invalid or unreadable server environment file')
    if os.name=='nt' and os.environ.get('LOCAL_API_RUNTIME')=='wsl':
        parser.error('Room worker migrated to Investify WSL; do not open the historical Windows database')
    from delivery.worker import process_one
    from store import DEFAULT_DB_PATH
    database=args.db or DEFAULT_DB_PATH
    stopping=[False]
    def stop(*_):stopping[0]=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    while not stopping[0]:
        job=process_one(database)
        if not args.watch:
            print('Processed one room job.' if job else 'No eligible queued room job.')
            break
        if not job:time.sleep(2)
