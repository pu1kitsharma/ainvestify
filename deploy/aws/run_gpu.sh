#!/bin/bash
# Starts/stops the existing GPU instance; never creates or terminates instances.
# Git Bash: AWS=/path/to/aws.exe WSL_DISTRO=Ubuntu bash deploy/aws/run_gpu.sh start
# WSL_DISTRO defaults to WSL's default distro. SSH_USER defaults to ubuntu.
# SSH_KEY is a WSL path (default: ~/.ssh/id_ed25519 inside that distro).
# The tunnel lives in WSL so the worker uses http://127.0.0.1:11435 even with WSL NAT.
# MAX_MONTH_HOURS must match setup_guard.sh (default 20). Hours are guard estimates.
set +x
set -euo pipefail
AWS=${AWS:-aws}
export MSYS_NO_PATHCONV=1
export AWS_PAGER=
export AWS_CLI_AUTO_PROMPT=off
REGION=ap-south-1
MAX_MONTH_HOURS=${MAX_MONTH_HOURS:-20}
SSH_USER=${SSH_USER:-ubuntu}
SSH_KEY=${SSH_KEY:-}
WSL=(wsl.exe)
[ -z "${WSL_DISTRO:-}" ] || WSL+=(-d "$WSL_DISTRO")

die() { echo "$*" >&2; exit 1; }
aws_call() { "$AWS" --region "$REGION" "$@" 2>/dev/null; }

# WSL owns both the SSH process and its control socket. Stop only addresses that
# socket; no PID files, process-name matching, or kills of unrelated processes.
WSL_HELPER=$(cat <<'WSL'
set +x
set -euo pipefail
umask 077
state="$HOME/.local/state/deal-gpu"
mkdir -p "$state"
for tool in ssh curl flock; do
  command -v "$tool" >/dev/null || { echo "WSL needs $tool" >&2; exit 1; }
done
exec 8>"$state/operation.lock"
flock -w 30 8 || { echo 'Another tunnel operation is busy' >&2; exit 1; }

stop_tunnel() {
  rm -f "$state/enabled"
  for attempt in {1..20}; do
    if [ -S "$state/control" ]; then
      ssh -F /dev/null -S "$state/control" -O exit deal-gpu >/dev/null 2>&1 || true
    fi
    if flock -n "$state/loop.lock" true; then
      rm -f "$state/control" "$state/ready"
      return 0
    fi
    sleep 1
  done
  echo 'Tunnel did not close; its reconnect flag has been removed' >&2
  return 1
}

tunnel_loop() {
  local state=$1 host=$2 user=$3 key=$4 instance=$5
  exec 9>"$state/loop.lock"
  flock -n 9 || return 1
  trap 'rm -f "$state/ready" "$state/control"' EXIT
  printf 'ready\n' > "$state/ready"
  while [ -f "$state/enabled" ]; do
    ssh -F /dev/null -i "$key" -o IdentitiesOnly=yes -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new -o "HostKeyAlias=deal-gpu-$instance" \
      -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -o ControlMaster=yes -o ControlPersist=no -S "$state/control" \
      -N -T -L 127.0.0.1:11435:127.0.0.1:11434 "$user@$host" \
      </dev/null >/dev/null 2>&1 || true
    [ -f "$state/enabled" ] || break
    sleep 3
  done
}

case "$1" in
  check)
    key=${2:-$HOME/.ssh/id_ed25519}
    [ -r "$key" ] || { echo 'SSH_KEY must name a readable private key inside WSL' >&2; exit 1; }
    ;;
  start)
    host=$2 user=$3 key=${4:-$HOME/.ssh/id_ed25519} instance=$5
    stop_tunnel
    : > "$state/enabled"
    # Close the operation lock in the detached child. Its separate loop lock
    # stays held across SSH reconnects and lets stop wait for a complete exit.
    nohup bash -c "$(declare -f tunnel_loop); tunnel_loop \"\$@\"" \
      deal-gpu "$state" "$host" "$user" "$key" "$instance" \
      8>&- </dev/null >/dev/null 2>&1 &
    for attempt in {1..10}; do
      [ ! -f "$state/ready" ] || exit 0
      sleep 1
    done
    stop_tunnel
    echo 'Tunnel supervisor failed to start' >&2
    exit 1
    ;;
  stop) stop_tunnel ;;
  health)
    [ -f "$state/enabled" ] && [ -S "$state/control" ] && \
      ssh -F /dev/null -S "$state/control" -O check deal-gpu >/dev/null 2>&1 && \
      curl --noproxy '*' -fsS --connect-timeout 2 --max-time 4 \
        http://127.0.0.1:11435/api/version 2>/dev/null | \
      grep -Eq '"version"[[:space:]]*:[[:space:]]*"[^"[:space:]]+'
    ;;
  *) exit 2 ;;
esac
WSL
)

wsl_tunnel() { "${WSL[@]}" -- bash -s -- "$@" <<< "$WSL_HELPER"; }

find_instance() {
  local ids
  ids=$(aws_call ec2 describe-instances \
    --filters Name=tag:Project,Values=deal-gpu \
      Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[].Instances[].InstanceId' --output text | tr -d '\r') || \
    die 'Could not find the tagged GPU instance'
  local found=()
  read -r -a found <<< "${ids//$'\n'/ }"
  [ "${#found[@]}" -eq 1 ] && [[ "${found[0]}" == i-* ]] || \
    die 'Expected exactly one existing instance tagged Project=deal-gpu'
  ID=${found[0]}
}

instance_field() {
  aws_call ec2 describe-instances --instance-ids "$ID" \
    --query "Reservations[0].Instances[0].$1" --output text | tr -d '\r'
}

ssh_rules() {
  aws_call ec2 describe-security-group-rules \
    --filters "Name=group-id,Values=$1" \
    --query 'SecurityGroupRules[?IsEgress==`false` && (IpProtocol==`"-1"` || ((IpProtocol==`"tcp"` || IpProtocol==`"6"`) && FromPort<=`22` && ToPort>=`22`))].SecurityGroupRuleId' \
    --output text | tr -d '\r'
}

restrict_ssh() {
  local ip octet vpc groups group name target= rules
  ip=$(curl --noproxy '*' -fsS --connect-timeout 5 --max-time 15 \
    https://checkip.amazonaws.com 2>/dev/null | tr -d '\r\n') || die 'Could not discover the current public IPv4 address'
  [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die 'Invalid public IPv4 address'
  for octet in ${ip//./ }; do
    [ "$((10#$octet))" -le 255 ] || die 'Invalid public IPv4 address'
  done
  vpc=$(instance_field VpcId) || die 'Could not read instance VPC'
  groups=$(instance_field 'SecurityGroups[].GroupId') || die 'Could not read attached security groups'
  for group in $groups; do
    name=$(aws_call ec2 describe-security-groups --group-ids "$group" \
      --query 'SecurityGroups[0].GroupName' --output text | tr -d '\r') || die 'Could not inspect security group'
    if [ "$name" = deal-gpu ]; then
      [ -z "$target" ] || die 'More than one deal-gpu security group is attached'
      target=$group
    else
      rules=$(ssh_rules "$group") || die 'Could not inspect attached SSH rules'
      [ -z "$rules" ] || die 'Another attached security group permits SSH; remove that access first'
    fi
  done
  [ -n "$target" ] || die "No deal-gpu security group is attached in $vpc"
  rules=$(ssh_rules "$target") || die 'Could not inspect deal-gpu SSH rules'
  # Revoke by rule ID: includes IPv6, group sources and ranges/all protocols
  # that permit port 22. Other rules remain as they were.
  for group in $rules; do
    aws_call ec2 revoke-security-group-ingress --group-id "$target" \
      --security-group-rule-ids "$group" >/dev/null || die 'Could not revoke old SSH access'
  done
  aws_call ec2 authorize-security-group-ingress --group-id "$target" \
    --protocol tcp --port 22 --cidr "$ip/32" >/dev/null || die 'Could not allow SSH from the current address'
  echo 'SSH access restricted to the current public IPv4 address'
}

start_gpu() {
  wsl_tunnel check "$SSH_KEY" || die 'WSL tunnel prerequisites are missing'
  find_instance
  STATE=$(instance_field State.Name) || die 'Could not read instance state'
  # Restrict access before boot or SSH polling, so an old address is never used.
  restrict_ssh
  if [ "$STATE" = stopping ]; then
    aws_call ec2 wait instance-stopped --instance-ids "$ID" || die 'Timed out waiting for the instance to stop'
    STATE=stopped
  fi
  case "$STATE" in
    stopped)
      aws_call ec2 start-instances --instance-ids "$ID" >/dev/null || die 'Could not start GPU instance'
      ;;
    pending|running) ;;
    *) die "Cannot start instance in state $STATE" ;;
  esac
  echo "Waiting for $ID to run and accept SSH"
  aws_call ec2 wait instance-running --instance-ids "$ID" || die 'Timed out waiting for running state; use stop to stop the instance'
  local host attempt
  host=$(instance_field PublicIpAddress) || die 'Could not read public IP; use stop to stop the instance'
  [ -n "$host" ] && [ "$host" != None ] || die 'Instance has no public IPv4 address; use stop to stop it'
  wsl_tunnel start "$host" "$SSH_USER" "$SSH_KEY" "$ID" || die 'Could not start the tunnel; use stop to stop the instance'
  for attempt in {1..60}; do
    if wsl_tunnel health; then
      echo "$ID running; SSH and /api/version verified"
      echo 'WSL worker endpoint: http://127.0.0.1:11435 (tunnel reconnects automatically)'
      return 0
    fi
    sleep 3
  done
  die 'SSH or /api/version did not become ready; tunnel keeps retrying. Use stop to stop the instance'
}

status_gpu() {
  find_instance
  STATE=$(instance_field State.Name) || die 'Could not read instance state'
  echo "$ID: $STATE ($REGION)"
  local month hours result=0
  month=$(date -u +%Y-%m)
  # get-parameters returns an empty list for a missing month; auth/network
  # errors still fail, rather than being reported as zero hours used.
  if hours=$(aws_call ssm get-parameters --names "/deal-gpu/hours/$month" \
    --query 'Parameters[0].Value' --output text | tr -d '\r'); then
    [ "$hours" != None ] || hours=0
    if [[ "$hours" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
      echo "$month (UTC): $hours / $MAX_MONTH_HOURS hours (guard estimate)"
    else
      echo 'Monthly hours: invalid SSM value' >&2
      result=1
    fi
  else
    echo "Monthly hours: unavailable / $MAX_MONTH_HOURS hour limit" >&2
    result=1
  fi
  if wsl_tunnel health; then
    echo 'Tunnel: healthy; WSL 127.0.0.1:11435 /api/version responds'
  else
    echo 'Tunnel: down or model server unavailable'
    result=1
  fi
  return "$result"
}

stop_gpu() {
  local result=0
  # A local WSL failure must not prevent stopping the billable instance.
  wsl_tunnel stop || { echo 'Could not confirm tunnel closure' >&2; result=1; }
  find_instance
  STATE=$(instance_field State.Name) || die 'Could not read instance state'
  case "$STATE" in
    stopped) ;;
    stopping) ;;
    pending)
      aws_call ec2 wait instance-running --instance-ids "$ID" || die 'Could not wait for pending instance before stopping'
      aws_call ec2 stop-instances --instance-ids "$ID" >/dev/null || die 'Could not stop GPU instance'
      ;;
    running)
      aws_call ec2 stop-instances --instance-ids "$ID" >/dev/null || die 'Could not stop GPU instance'
      ;;
    *) die "Cannot stop instance in state $STATE" ;;
  esac
  aws_call ec2 wait instance-stopped --instance-ids "$ID" || die 'Timed out waiting for stopped state'
  STATE=$(instance_field State.Name) || die 'Could not confirm instance state'
  [ "$STATE" = stopped ] || die "Instance state is $STATE; stopped was expected"
  echo "$ID: stopped (confirmed)"
  [ "$result" -ne 0 ] || echo 'Tunnel: closed (reconnection disabled)'
  return "$result"
}

[ "$#" -eq 1 ] || die 'Usage: bash deploy/aws/run_gpu.sh {start|status|stop}'
case "$1" in start|status|stop) ;; *) die 'Usage: bash deploy/aws/run_gpu.sh {start|status|stop}' ;; esac
[[ "$MAX_MONTH_HOURS" =~ ^[0-9]+([.][0-9]+)?$ ]] || die 'MAX_MONTH_HOURS must be numeric'
command -v "$AWS" >/dev/null || die 'AWS must point to the AWS CLI binary'
command -v wsl.exe >/dev/null || die 'wsl.exe is required'
case "$1" in
  start) start_gpu ;;
  status) status_gpu ;;
  stop) stop_gpu ;;
esac
