#!/usr/bin/env python3
"""Explicit opt-in local banker experiment. No downloads, training or cloud."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.runtime.banker_session import run_banker_session, validate_case
from agents.runtime.loop import RepairPolicy, validate_endpoint


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model',default='qwen3.5:9b')
    parser.add_argument('--endpoint',default='http://127.0.0.1:11434/v1')
    parser.add_argument('--passes',type=int,choices=(1,2,3),default=1)
    parser.add_argument('--scope',choices=('full','historical','pnl'),default='full')
    parser.add_argument('--mode',choices=('single','blocks'),default='single',help='blocks = small-block task ledger')
    parser.add_argument('--profile',choices=('default','diagnostic'),default='default',
        help='diagnostic = explicit larger limits (labelled in the report); default keeps 120s/6 calls')
    parser.add_argument('--no-repair',action='store_true',help='original fail-closed behavior: first invalid tool call ends the pass')
    parser.add_argument('--repair-consecutive',type=int,default=2)
    parser.add_argument('--repair-total',type=int,default=6)
    parser.add_argument('--infra-resume',action='store_true',help='allow ONE labelled resume after an infra fault (empty frame/connection)')
    parser.add_argument('--stop-on-block-failure',action='store_true')
    parser.add_argument('--blocks',default=None,help='comma separated block ids (default: all blocks of the scope)')
    parser.add_argument('--pass-seconds',type=float,default=None,help='per pass (single mode) seconds')
    parser.add_argument('--pass-calls',type=int,default=None)
    parser.add_argument('--block-seconds',type=float,default=None)
    parser.add_argument('--block-calls',type=int,default=None)
    parser.add_argument('--block-tokens',type=int,default=None)
    parser.add_argument('--output-tokens',type=int,default=None,help='per-call generation cap (512-4096)')
    parser.add_argument('--call-seconds',type=float,default=None,help='per model call timeout')
    parser.add_argument('--session-seconds',type=float,default=1800,help='blocks mode: stop starting blocks after this many seconds')
    parser.add_argument('--run',action='store_true',help='Explicitly authorize bounded installed-local inference')
    args=parser.parse_args(argv)
    if args.case.stat().st_size>256_000: raise ValueError('case exceeds input byte bound')
    case=validate_case(json.loads(args.case.read_text()))
    validate_endpoint(args.endpoint)
    if not args.run:
        print(json.dumps({'status':'validated_not_run','model':args.model,'endpoint':args.endpoint,
            'scope':args.scope,'full_banker':False,'max_modeling_passes':args.passes,'writer_passes':1,'bounds_per_pass_or_block':{'calls':(args.block_calls if args.mode=='blocks' else args.pass_calls) or 6,'seconds':(args.block_seconds if args.mode=='blocks' else args.pass_seconds) or 120,'profile':args.profile},'mode':args.mode,'repair':not args.no_repair,
            'model_installation':'not_checked','no_network_or_inference':True}))
        return 0
    def limits(seconds,calls):
        out={'profile':args.profile}
        if seconds is not None: out['seconds']=seconds
        if calls is not None: out['calls']=calls
        if args.output_tokens is not None: out['output_tokens']=args.output_tokens
        if args.call_seconds is not None: out['call_seconds']=args.call_seconds
        return out
    pass_args=limits(args.pass_seconds,args.pass_calls)
    block_args=limits(args.block_seconds,args.block_calls)
    if args.block_tokens is not None: block_args['tokens']=args.block_tokens
    if args.mode=='blocks': pass_args={'profile':args.profile}  # unused in blocks mode (writer uses the block budget)
    else: block_args={'profile':args.profile}
    repair=None if args.no_repair else RepairPolicy(args.repair_consecutive,args.repair_total)
    diag=args.profile=='diagnostic'
    from agents.runtime.banker_session import NativeOllamaTransport
    factory=(lambda: NativeOllamaTransport(max_timeout=600,num_predict_cap=4096)) if diag else None
    report=run_banker_session(case=case,output=args.output,model=args.model,endpoint=args.endpoint,passes=args.passes,scope=args.scope,
        mode=args.mode,repair=repair,budget_args=pass_args,block_budget_args=block_args,session_seconds=args.session_seconds,
        infra_resume=args.infra_resume,stop_on_block_failure=args.stop_on_block_failure,
        block_ids=args.blocks.split(',') if args.blocks else None,transport_factory=factory)
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='draft_exported' else 1

if __name__=='__main__': raise SystemExit(main())
