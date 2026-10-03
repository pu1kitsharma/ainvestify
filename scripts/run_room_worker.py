"""Run one bounded durable room job. Invoke from an external scheduler, not FastAPI."""
import argparse
from pathlib import Path
import sys
import signal
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from delivery.worker import process_one
from store import DEFAULT_DB_PATH

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=DEFAULT_DB_PATH)
    parser.add_argument('--watch',action='store_true',help='One external worker; finish current bounded job on termination')
    args=parser.parse_args()
    stopping=[False]
    def stop(*_):stopping[0]=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    while not stopping[0]:
        job=process_one(args.db)
        if not args.watch:
            print('Processed one room job.' if job else 'No eligible queued room job.')
            break
        if not job:time.sleep(2)
