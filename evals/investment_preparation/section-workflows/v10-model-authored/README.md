# v10 model-authored checkpoint — 15 September 2026

**Failed acceptance. Reliable fresh generation remains unfixed.** The user requested a thorough state log and Git push, then directed an immediate push. No new inference was started for this checkpoint.

Read [handoff §23](../../../../SESSION_HANDOFF.md#model-authored-reset) for the complete implementation, reset, failure sequence, operational state, verification limits and next-session prompt. [verification.json](verification.json) records the final checks. Only GoCardless exists in the new live workspace; no complete live v10 nine-section pack has been demonstrated.

| Evidence | Meaning |
| --- | --- |
| `source_run_9f834e02927b.json` | First search: three calls, partial, no company |
| `source_run_4513f7e6a177.json` | Second search: five calls, GoCardless retained, later extraction cancelled at deadline |
| `source_run_deb9bacc8d62.json` | Third search: two calls, failed, no accessible destinations |
| `lead_3f0aee42d7ad-first-workspace.json` | Automatic preparation's original failure |
| `preparation-second-failure.json` | Second preparation's original failure |
| `preparation-final-failure.json` | Final full workspace, revision 42, latest failure and both prior packs |
| `*-start.json` | Initial responses, not completion evidence |
| `*-checkpoint.json`, if present | Later read-only snapshot; does not overwrite earlier evidence |
| `manifest.json` | SHA-256 and sizes of this directory's artifacts, plus active implementation hashes |

Latest job `automation_26b2f9c3cfc1` failed after 61.186 seconds/two model calls with zero published sections. Its repair retained literal internal source IDs and a numerical rate. Inspection also found source meaning and financial reasoning errors; normal token counts do not support context overflow as the explanation. All original model answers remain unchanged.

Six live jobs used sixteen actual calls, including one cancelled request. Different code contracts were used across development iterations. The final empty-criteria/transport changes have no new live discovery evaluation. 258 focused tests, frontend build and lint pass; these are engineering checks, not investment-quality acceptance. Current readiness proposes narrative work and does not require an executable typed financial plan.

The old tenant was explicitly reset only after a consistent verified backup. Full SQLite data, backup, uploads and runtime files remain local and are not pushed. Older v9 complete reports are template-assisted historical evidence, not proof that this model-authored pipeline works. No manual replacement company text was supplied to make these failures appear successful.
