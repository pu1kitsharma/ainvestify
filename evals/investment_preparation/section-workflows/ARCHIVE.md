# Historical raw evaluation archive

The October 2026 repository cleanup consolidated 143 older, unlinked raw JSON
snapshots (41.91 MiB) into `archived-raw-2026-10-04.tar.gz` (7.99 MiB). Their
original relative paths, byte counts and SHA-256 digests are listed in
`archived-raw-2026-10-04.manifest.json`. The archive contains the original bytes;
no company response or result was rewritten. The existing Git history also
retains the original files.

Test fixtures, JSON files linked from Markdown indexes, and reports under
`final/`, `accepted/` and `verified/` remain at their original paths. New live
qualification output belongs under ignored `runtime_qualification/`, not here.

Verify the archive:

```sh
python3 scripts/check_historical_eval_archive.py
```

To inspect or restore an archived path, run from the repository root:

```sh
tar -tzf evals/investment_preparation/section-workflows/archived-raw-2026-10-04.tar.gz
tar -xzf evals/investment_preparation/section-workflows/archived-raw-2026-10-04.tar.gz -C /tmp
```

Extracting to `/tmp` leaves the source checkout unchanged. The manifest lets a
reviewer verify any extracted file against the saved digest.
