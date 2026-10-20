# GPU run plan (fill in and approve BEFORE any GPU start)

No GPU VM may be started until this file (a filled copy, one per run or block of runs)
exists and `delivery/gpu_lifecycle.py` is given its path as `run_plan_ref`. Template only;
nothing is approved by this file existing. Prices below are estimates until re-verified.

| Field | Value |
|---|---|
| Plan ID / date | |
| Approver (named person, not an agent) | |
| Approval date/time and how given (message, signature) | |
| Machine | A100 80GB spot (`a2-ultragpu-1g`) / fallback A100 40GB (`a2-highgpu-1g`) |
| Region/zone | asia-south1 / |
| Rate source and date re-verified in GCP calculator | INR ___ /h, verified on ___ (`deploy/gcp/gpu_rates.json` has `verify_before_use: false`) |
| Pool used so far this month (`GpuSpendLedger.usage()`) | ___ h / 110 h, INR ___ / 22,000 |

## Runs

| # | Purpose (bake-off / sampling / SFT / eval) | Model + adapter | Dataset (private? where stored) | Planned hours | Expected INR (hours x rate) | Checkpoint interval (~20 min) | Success measure |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| **Total** | | | | | | | |

Expected total must leave at least 15% of both the 110 h pool and INR 22,000 unreserved.

## Stop conditions (all must be configured, not just listed)

- [ ] Ledger reservation made for the planned hours (`GpuSpendLedger.reserve`) and run stops when it is exhausted.
- [ ] Idle timeout minutes: ___ (default 15).
- [ ] Startup timeout minutes: ___ (default 15); unhealthy VM is stopped.
- [ ] Budget kill switch deployed and tested with a synthetic message; `DRY_RUN=false` set only after that test.
- [ ] Abort rule if the first ___ minutes show reward/loss unchanged or NaN.
- [ ] Preemption policy: re-queue from the last checkpoint at most ___ times, then stop and ask.
- [ ] Manual stop command and who runs it: `gcloud compute instances stop <instance> --zone <zone> --project <project>`.

## Data and privacy

- [ ] Only data classes approved for training are listed above; private references need written approval.
- [ ] Bucket is the India bucket; no data leaves the project VPC; no hosted model API is used.

## Close-out (fill after the run)

Actual hours ___, actual INR ___, ledger settled yes/no, VM confirmed STOPPED yes/no, artifacts saved to bucket ___, issues ___.
