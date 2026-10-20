#!/usr/bin/env bash
# Runs as root on every VM boot (spot restarts included). Idempotent.
set -euo pipefail
md() { curl -fsS -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
BUCKET="$(md bucket)"; SECRET="$(md token-secret)"; DISK="$(md weights-disk)"
md vllm-config > /etc/vllm.env; set -a; . /etc/vllm.env; set +a

# 1. Weights disk (persistent). Format only if blank.
DEV="/dev/disk/by-id/google-${DISK}"
blkid "$DEV" >/dev/null 2>&1 || mkfs.ext4 -F "$DEV"
mkdir -p /mnt/weights; mountpoint -q /mnt/weights || mount -o discard,defaults "$DEV" /mnt/weights

# 2. Sync base weights + adapters + latest checkpoint from the India bucket (no public internet needed).
gcloud storage rsync -r "gs://${BUCKET}/models/base" /mnt/weights/base || true
gcloud storage rsync -r "gs://${BUCKET}/adapters" /mnt/weights/adapters || true

# 3. vLLM (first boot needs Cloud NAT for pip; afterwards the venv is on the weights disk).
if [ ! -x /mnt/weights/venv/bin/vllm ]; then
  python3 -m venv /mnt/weights/venv
  /mnt/weights/venv/bin/pip install "vllm==${VLLM_VERSION}"
fi

# 4. Bearer token from Secret Manager. Never written to logs.
umask 077
gcloud secrets versions access latest --secret="$SECRET" > /run/vllm-token
PRIVATE_IP="$(hostname -I | awk '{print $1}')"

ARGS=(serve "$MODEL" --host "$PRIVATE_IP" --port "$PORT" --served-model-name "$SERVED_MODEL_NAME"
      --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION")
# Tool calling for the agent runtime (parser name for Qwen-family models; confirm with `vllm serve --help`).
ARGS+=(--enable-auto-tool-choice --tool-call-parser "${TOOL_CALL_PARSER:-hermes}")
# vLLM reads the key from VLLM_API_KEY, so it never appears in argv, the unit file or logs.
printf 'VLLM_API_KEY=%s\n' "$(cat /run/vllm-token)" > /run/vllm.secret.env; chmod 600 /run/vllm.secret.env
# Lets training.gpu_generate load newly trained adapters without restarting the server (unverified; see GPU_MACHINE_SETUP.md).
printf 'VLLM_ALLOW_RUNTIME_LORA_UPDATING=True\n' >> /run/vllm.secret.env
if [ "${ENABLE_LORA:-0}" = "1" ]; then
  ARGS+=(--enable-lora --max-loras "$MAX_LORAS" --max-lora-rank "$MAX_LORA_RANK")
  # shellcheck disable=SC2206
  MODS=($LORA_MODULES); [ ${#MODS[@]} -gt 0 ] && ARGS+=(--lora-modules "${MODS[@]}")
fi
cat > /etc/systemd/system/vllm.service <<UNIT
[Unit]
Description=vLLM OpenAI-compatible server (private IP only)
After=network-online.target
[Service]
EnvironmentFile=/run/vllm.secret.env
ExecStart=/mnt/weights/venv/bin/vllm ${ARGS[@]@Q}
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable --now vllm.service
