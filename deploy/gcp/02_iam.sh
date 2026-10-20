#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/env.sh"
require_var PROJECT_ID
P="--project=$PROJECT_ID"
run gcloud iam service-accounts create gpu-vm --display-name="GPU VM (vLLM, training)" $P
run gcloud iam service-accounts create gpu-lifecycle --display-name="App: start/stop GPU VM" $P
run gcloud iam service-accounts create gpu-killswitch --display-name="Budget kill switch" $P
# Custom role: only what the app and the kill switch need on instances.
run gcloud iam roles create gpuVmOperator --project="$PROJECT_ID" --title="GPU VM start/stop/get" \
  --permissions=compute.instances.get,compute.instances.start,compute.instances.stop,compute.zoneOperations.get
run gcloud iam roles create gpuVmStopper --project="$PROJECT_ID" --title="GPU VM stop only" \
  --permissions=compute.instances.get,compute.instances.stop,compute.zoneOperations.get
run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:gpu-lifecycle@${PROJECT_ID}.iam.gserviceaccount.com" --role="projects/${PROJECT_ID}/roles/gpuVmOperator"
run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:gpu-killswitch@${PROJECT_ID}.iam.gserviceaccount.com" --role="projects/${PROJECT_ID}/roles/gpuVmStopper"
run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:gpu-vm@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/logging.logWriter"
# Bucket / secret bindings are resource-level (03_storage.sh), not project-wide.
