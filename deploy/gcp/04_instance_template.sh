#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/env.sh"
require_var PROJECT_ID
# Spot A100 80GB. STOP (not DELETE) on preemption so the boot disk and weights disk survive.
# --no-address: NO public IP. a2-* machine types include the GPUs; no --accelerator flag.
run gcloud compute instance-templates create banker-gpu-template \
  --project="$PROJECT_ID" --region="$REGION" --machine-type="$MACHINE_TYPE" \
  --provisioning-model=SPOT --instance-termination-action=STOP --maintenance-policy=TERMINATE \
  --network="$NETWORK" --subnet="$SUBNET" --no-address \
  --service-account="gpu-vm@${PROJECT_ID}.iam.gserviceaccount.com" --scopes=cloud-platform \
  --image-family=common-cu124-ubuntu-2204-py310 --image-project=deeplearning-platform-release \
  --boot-disk-size=100GB --boot-disk-type=pd-balanced \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --metadata-from-file=startup-script="$(dirname "$0")/startup-script.sh",vllm-config="$(dirname "$0")/vllm_config.env" \
  --metadata=bucket="$BUCKET",token-secret="$TOKEN_SECRET",weights-disk="$WEIGHTS_DISK",enable-oslogin=TRUE
