# WS-C/F local foundation evidence — 15 October 2026

35 synthetic software tests pass (`python3 -m pytest tests/envs -q`).
`synthetic-iteration/` preserves one fictional sample, reward, selected JSONL,
source/split manifest, mock trainer declaration and two held-out predictions'
score report. All files describe dry-run plumbing. No real company, private
reference, training example or accepted investor material was generated.

Implemented: mandatory E1–E7 dimensions, independent externally supplied keys,
missing/unsupported zero rewards, flag precision/recall, duplicate/unanswered case
handling; public-only company/sector/family/hash split checks; disabled source
registry; exclusive mode-0600 score reports; bounded injected sample→score→filter
→mock trainer→held-out evaluator with immutable raw samples and failure receipts.

Limitations: no filings collected, independently adjudicated public gold, actual
artifact inspection, corpus-wide correctness, model inference, MLX/QLoRA round,
trained adapter, memorisation probe, visual review or investor acceptance. Callback
results are unverified declarations. Real training mode deliberately refuses.
Only the focused new suite was run here; repository-wide acceptance is unrun.
Private data and derived labels remain excluded. Rights review remains pending
for every listed source candidate. Company aliases and supplied hashes require
independent source/entity validation. See `training/envs/README.md` for schemas.
