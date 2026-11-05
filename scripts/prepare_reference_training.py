"""Prepare local private reference review packets; never train or promote holdouts."""
import argparse
import json
from pathlib import Path

from training.reference_intake import prepare_reference_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference_manifest', type=Path)
    parser.add_argument('archive_manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--archive-root', type=Path, required=True)
    parser.add_argument('--source-use-approval-id', required=True)
    args = parser.parse_args()
    try:
        report = prepare_reference_review(args.reference_manifest, args.archive_manifest, args.output,
            private_root=args.private_root, archive_root=args.archive_root,
            source_use_approval_id=args.source_use_approval_id)
    except Exception:
        parser.exit(1, 'Private reference preparation failed; inspect approved local source metadata.\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
