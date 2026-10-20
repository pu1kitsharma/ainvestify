#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"; source "$(dirname "$0")/env.sh"
require_var PROJECT_ID; require_var BILLING_ACCOUNT
run gcloud projects create "$PROJECT_ID" --name="agentic-banker-training"
run gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
run gcloud services enable compute.googleapis.com storage.googleapis.com secretmanager.googleapis.com \
  pubsub.googleapis.com cloudfunctions.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  billingbudgets.googleapis.com iap.googleapis.com logging.googleapis.com --project="$PROJECT_ID"
run gcloud compute networks create "$NETWORK" --subnet-mode=custom --project="$PROJECT_ID"
# Private Google Access lets the VM reach GCS/Secret Manager without a public IP.
run gcloud compute networks subnets create "$SUBNET" --network="$NETWORK" --region="$REGION" \
  --range="$SUBNET_RANGE" --enable-private-ip-google-access --project="$PROJECT_ID"
# Cloud NAT is only for package/model downloads at first boot; delete it once weights are on the disk.
run gcloud compute routers create banker-router --network="$NETWORK" --region="$REGION" --project="$PROJECT_ID"
run gcloud compute routers nats create banker-nat --router=banker-router --region="$REGION" \
  --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges --project="$PROJECT_ID"
run gcloud compute firewall-rules create banker-allow-iap-ssh --network="$NETWORK" --direction=INGRESS \
  --allow=tcp:22 --source-ranges=35.235.240.0/20 --target-service-accounts="gpu-vm@${PROJECT_ID}.iam.gserviceaccount.com" --project="$PROJECT_ID"
run gcloud compute firewall-rules create banker-allow-vllm-internal --network="$NETWORK" --direction=INGRESS \
  --allow=tcp:8000 --source-ranges="$SUBNET_RANGE" --target-service-accounts="gpu-vm@${PROJECT_ID}.iam.gserviceaccount.com" --project="$PROJECT_ID"
run gcloud compute firewall-rules create banker-deny-all-ingress --network="$NETWORK" --direction=INGRESS \
  --action=DENY --rules=all --priority=65000 --source-ranges=0.0.0.0/0 --project="$PROJECT_ID"
