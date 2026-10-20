#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/env.sh"
require_var PROJECT_ID
run gcloud compute instances create "$GPU_INSTANCE" --source-instance-template=banker-gpu-template \
  --zone="$ZONE" --project="$PROJECT_ID" --disk=name="$WEIGHTS_DISK",device-name="$WEIGHTS_DISK",mode=rw,boot=no
# A fresh instance is RUNNING and billing. Stop it immediately; start only via delivery/gpu_lifecycle.py after ledger reservation.
run gcloud compute instances stop "$GPU_INSTANCE" --zone="$ZONE" --project="$PROJECT_ID"
