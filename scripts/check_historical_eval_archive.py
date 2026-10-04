"""Verify the byte-for-byte historical evaluation archive without extracting it."""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'evals/investment_preparation/section-workflows/archived-raw-2026-10-04.manifest.json'


def main() -> None:
    record = json.loads(MANIFEST.read_text())
    archive = ROOT / record['archive']
    entries = record['entries']
    expected = {row['path'] for row in entries}
    if len(expected) != len(entries):
        raise ValueError('Duplicate archived path')
    with tarfile.open(archive, 'r:gz') as source:
        if set(source.getnames()) != expected:
            raise ValueError('Archive membership differs from manifest')
        for row in entries:
            member = source.getmember(row['path'])
            if not member.isfile() or member.size != row['bytes']:
                raise ValueError(f"Archived size differs: {row['path']}")
            stream = source.extractfile(member)
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != row['sha256']:
                raise ValueError(f"Archived digest differs: {row['path']}")
    print(f'Verified {len(entries)} historical evaluation files in {archive.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
