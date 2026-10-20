# C1 public training-data factory (offline, 20 October 2026)

Code: `training/data/` (registry, taxonomy, collectors, `xbrl_tasks.py`, `build_corpus.py`).
Tests: `tests/training_data/` (`.venv/bin/python -m pytest tests/training_data -q`).

`synthetic-fixture-run/` was generated from three hand-written SYNTHETIC XBRL-shaped
fixtures (software Dec FYE, hardware Sep FYE, consumer Jan FYE). Nothing is a real company
or a real figure. The run is plumbing-only: fixtures were treated as rights-approved in memory
solely so the leakage validator could run; coverage toward the gate counts them as zero.
`keys.jsonl` is mode 0600 and kept separate from `tasks.jsonl` so samplers never see answers.

No live SEC call was made: `RESEARCH_AGENT_CONTACT` was unset and every source is disabled in
`training/data/enabled_sources.json` (empty). To collect, the user must (1) set
`RESEARCH_AGENT_CONTACT='Org contact@email'`, (2) list `sec_edgar_companyfacts` in the enable
file, (3) review terms and set the registry `rights_status` to `public_training_approved`.

Schema gaps (scoring.py untouched): E1/E7 per-cell checks are encoded as `set` strings;
E3 `scenarios` and E6 `sections` are `unsupported`; E2 boolean checks are declarations;
keys are verifiable arithmetic, not independently adjudicated gold. E7 figures are synthetic
arithmetic drills, not market facts. SEBI and investor-deck collectors are disabled interfaces.
