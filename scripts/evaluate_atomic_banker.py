#!/usr/bin/env python3
"""Explicit opt-in three-call local structured P&L experiment; no retries."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.runtime.atomic_banker import run_atomic_banker,mapping_schema,strict_json
from agents.runtime.banker_session import validate_case
from agents.runtime.loop import validate_endpoint


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model',default='qwen3.5:4b')
    parser.add_argument('--endpoint',default='http://127.0.0.1:11434/v1')
    parser.add_argument('--stages',type=int,choices=(1,2,3),default=3)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if args.case.stat().st_size>256000:raise ValueError('case exceeds byte bound')
    case=validate_case(strict_json(args.case.read_text()))
    mapping_schema(case);validate_endpoint(args.endpoint)
    if not args.run:
        print(json.dumps({'status':'validated_not_run','scope':'historical_pnl','full_banker':False,
            'model':args.model,'no_network_or_inference':True,'maximum_requests':args.stages,'requested_stages':args.stages,'cumulative_seconds':120}))
        return 0
    report=run_atomic_banker(case=case,output=args.output,model=args.model,endpoint=args.endpoint,stages=args.stages)
    print(json.dumps(report,indent=2))
    return 0 if report['status'] in {'draft_exported','model_mapped_draft','model_written_draft'} else 1

if __name__=='__main__':raise SystemExit(main())
