#!/bin/bash
# Launches the one GPU instance: encrypted disk, SSH from one address only, IMDSv2, and a stop built into every boot.
# Run setup_guard.sh first. Usage: SSH_FROM=203.0.113.7 bash deploy/aws/launch_gpu.sh
set -euo pipefail
AWS=${AWS:-aws}
export MSYS_NO_PATHCONV=1
REGION=ap-south-1
TYPE=${TYPE:-g6e.2xlarge}
AMI=${AMI:-ami-0ef3a2eab02060c46}
DISK_GB=${DISK_GB:-100}
BOOT_STOP_MINUTES=${BOOT_STOP_MINUTES:-345}   # just inside the guard's session limit, in case the guard is down
KEY_FILE=${KEY_FILE:-$HOME/.ssh/id_ed25519.pub}

"$AWS" ec2 describe-key-pairs --region $REGION --key-names deal-gpu >/dev/null 2>&1 || \
  "$AWS" ec2 import-key-pair --region $REGION --key-name deal-gpu --public-key-material "fileb://$KEY_FILE" >/dev/null
VPC=$("$AWS" ec2 describe-vpcs --region $REGION --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text | tr -d '\r')
GROUP=$("$AWS" ec2 describe-security-groups --region $REGION --filters Name=group-name,Values=deal-gpu Name=vpc-id,Values="$VPC" --query 'SecurityGroups[0].GroupId' --output text | tr -d '\r')
if [ "$GROUP" = None ]; then
  GROUP=$("$AWS" ec2 create-security-group --region $REGION --group-name deal-gpu --description 'GPU instance: SSH from one address only' --vpc-id "$VPC" --query GroupId --output text | tr -d '\r')
  "$AWS" ec2 authorize-security-group-ingress --region $REGION --group-id "$GROUP" --protocol tcp --port 22 --cidr "$SSH_FROM/32" >/dev/null
fi
cat > .deal-gpu-user-data <<EOF
#!/bin/bash
# Every boot schedules a stop, so a forgotten machine ends even if the cloud guard fails.
cat > /etc/systemd/system/deal-gpu-stop.service <<UNIT
[Unit]
Description=Stop this machine after a fixed time
[Service]
Type=oneshot
ExecStart=/sbin/shutdown -h +$BOOT_STOP_MINUTES
[Install]
WantedBy=multi-user.target
UNIT
systemctl enable --now deal-gpu-stop.service
EOF
trap 'rm -f .deal-gpu-user-data' EXIT
launch() {
  "$AWS" ec2 run-instances --region $REGION --image-id "$AMI" --instance-type "$TYPE" --count 1 --key-name deal-gpu --security-group-ids "$GROUP" \
    --subnet-id "$1" --associate-public-ip-address --instance-initiated-shutdown-behavior stop --user-data file://.deal-gpu-user-data \
    --metadata-options HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1 \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Project,Value=deal-gpu},{Key=Name,Value=deal-gpu}]' 'ResourceType=volume,Tags=[{Key=Project,Value=deal-gpu}]' \
    "${@:2}" --query 'Instances[0].InstanceId' --output text
}
SUBNETS=$("$AWS" ec2 describe-subnets --region $REGION --filters Name=default-for-az,Values=true --query 'Subnets[].SubnetId' --output text | tr -d '\r')
FIRST=${SUBNETS%%[[:space:]]*}
OUT=$(launch "$FIRST" --dry-run 2>&1 || true)
case "$OUT" in *DryRunOperation*) echo 'dry run passed';; *) echo "dry run failed: $OUT" >&2; exit 1;; esac
[ "${DRY_ONLY:-}" = 1 ] && exit 0
for SUBNET in $SUBNETS; do
  if ID=$(launch "$SUBNET" 2>/tmp/deal-gpu-launch.err); then
    echo "launched $ID"
    "$AWS" ec2 wait instance-running --region $REGION --instance-ids "$(echo "$ID" | tr -d '\r')"
    "$AWS" ec2 describe-instances --region $REGION --instance-ids "$(echo "$ID" | tr -d '\r')" --query 'Reservations[0].Instances[0].[InstanceId,PublicIpAddress,Placement.AvailabilityZone,InstanceType,BlockDeviceMappings[0].Ebs.VolumeId]' --output text
    exit 0
  fi
  cat /tmp/deal-gpu-launch.err >&2
done
echo 'no capacity in either zone' >&2
exit 1
