#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/env.sh"
require_var PROJECT_ID; require_var BILLING_ACCOUNT
HERE="$(cd "$(dirname "$0")" && pwd)"
run gcloud pubsub topics create banker-budget-alerts --project="$PROJECT_ID"
run gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name="banker-gpu-monthly" \
  --budget-amount="${MONTHLY_BUDGET_INR}${BUDGET_CURRENCY}" --filter-projects="projects/${PROJECT_ID}" \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=0.95 --threshold-rule=percent=1.0 \
  --notifications-rule-pubsub-topic="projects/${PROJECT_ID}/topics/banker-budget-alerts"
# The function starts in DRY_RUN=true (logs only). Flip to false after the synthetic-message test.
run gcloud functions deploy banker-kill-switch --gen2 --runtime=python312 --region="$REGION" --project="$PROJECT_ID" \
  --source="$HERE/kill_switch" --entry-point=stop_gpu_vm --trigger-topic=banker-budget-alerts \
  --service-account="gpu-killswitch@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars="GCP_PROJECT=${PROJECT_ID},GPU_ZONE=${ZONE},GPU_INSTANCES=${GPU_INSTANCE},KILL_THRESHOLD=0.95,DRY_RUN=true"
