#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/env.sh"
require_var PROJECT_ID; require_var BUCKET
P="--project=$PROJECT_ID"
# India bucket; Google-managed encryption at rest (add --default-encryption-key=<CMEK> if a KMS key is created).
run gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access --public-access-prevention $P
run gcloud storage buckets update "gs://$BUCKET" --versioning $P
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:gpu-vm@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/storage.objectAdmin
# Weights disk (persistent; survives spot preemption/stop).
run gcloud compute disks create "$WEIGHTS_DISK" --size="${WEIGHTS_DISK_GB}GB" --type=pd-balanced --zone="$ZONE" $P
run gcloud compute resource-policies create snapshot-schedule banker-daily --region="$REGION" \
  --max-retention-days=7 --daily-schedule --start-time=21:00 --on-source-disk-delete=keep-auto-snapshots $P
run gcloud compute disks add-resource-policies "$WEIGHTS_DISK" --resource-policies=banker-daily --zone="$ZONE" $P
# Token secret: create the secret container only. Put the value in with: head -c 32 /dev/urandom | base64 | gcloud secrets versions add ... --data-file=-
run gcloud secrets create "$TOKEN_SECRET" --replication-policy=user-managed --locations="$REGION" $P
run gcloud secrets add-iam-policy-binding "$TOKEN_SECRET" --member="serviceAccount:gpu-vm@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor $P
