#!/usr/bin/env python3
"""Score local JSON predictions against an independently supplied JSON answer key.

Inputs are JSON arrays using training.envs.scoring contracts. No inference,
source fetching, private-reference gold construction or acceptance decision.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from training.envs import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--answer-key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New report path; existing reports preserved')
    args = parser.parse_args()
    report = evaluate(json.loads(args.predictions.read_text()), json.loads(args.answer_key.read_text()))
    # Exclusive creation and restrictive mode: supplied keys may contain private data.
    import os
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'cases': len(report['cases']), 'mean_reward': report['mean_reward'], 'investor_acceptance': False}))


if __name__ == '__main__':
    main()
