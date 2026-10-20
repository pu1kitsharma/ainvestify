# GCP bring-up checklist (project resources) -- nothing here has been run

Order matters. Every script defaults to dry run; read the printed commands first.

1. [user] Billing upgrade + quota granted (see deployment/GPU_QUOTA_REQUEST.md).
2. [user] Fill `env.sh` from `env.example`; fill and approve `deployment/GPU_RUN_PLAN_TEMPLATE.md`.
3. [user] Re-verify prices in the GCP calculator; edit `gpu_rates.json` (`verify_before_use: false`).
4. `./01_project_and_network.sh` -- APIs, VPC, private subnet, Cloud NAT, firewall (IAP SSH + in-VPC 8000 only).
5. `./02_iam.sh` -- three least-privilege service accounts + custom roles.
6. `./03_storage.sh` -- India bucket (uniform access, public-access-prevention, versioning), weights disk, daily snapshot schedule, token secret.
7. `./04_instance_template.sh` -- spot A100 80GB template (no public IP) using `startup-script.sh`.
8. `./05_budget_kill_switch.sh` -- Pub/Sub topic, budget (50/80/95/100%), Cloud Function from `kill_switch/`.
   Test it with a synthetic message first (tests/gpu/test_kill_switch.py runs the logic locally).
   DRY_RUN env on the function defaults to "true": flip to "false" only after the end-to-end test on a INR 0/INR 1 test budget.
9. `./06_create_instance.sh` creates the VM STOPPED-ready; start it only through `delivery/gpu_lifecycle.py`.

Hard stops: ledger pool 110 GPU-h and INR 22,000 (agents/inference/spend_guard.py), idle stop (default 15 min),
budget kill switch at 95%, and a manual `gcloud compute instances stop`.
Remember: the budget alert lags real spend by hours; the ledger and idle-stop are the first line of defence.
