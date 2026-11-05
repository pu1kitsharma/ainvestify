#!/bin/bash
# Runs on the GPU instance. Installs a pinned model server, private to this machine, and fetches the models in $MODELS.
# The release is checked against its published checksum before anything from it runs.
set -euo pipefail
VERSION=${OLLAMA_VERSION:-v0.40.11}
ARCHIVE=ollama-linux-amd64.tar.zst
BASE=https://github.com/ollama/ollama/releases/download/$VERSION
WORK=$(mktemp -d)
cd "$WORK"
curl -fsSLO "$BASE/$ARCHIVE"
curl -fsSLO "$BASE/sha256sum.txt"
grep " \./$ARCHIVE\$\| $ARCHIVE\$" sha256sum.txt | sed 's# \./# #' | sha256sum -c -
sudo tar --zstd -xf "$ARCHIVE" -C /usr/local
id ollama >/dev/null 2>&1 || sudo useradd -r -s /usr/sbin/nologin -U -m -d /var/lib/ollama ollama
sudo tee /etc/systemd/system/ollama.service >/dev/null <<'EOF'
[Unit]
Description=Model server, reachable only from this machine
After=network-online.target
[Service]
User=ollama
Group=ollama
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=3
Environment=HOME=/var/lib/ollama
# Loopback only: the laptop reaches it through the SSH tunnel.
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_KEEP_ALIVE=30m
Environment=OLLAMA_NUM_PARALLEL=1
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
for attempt in 1 2 3 4 5 6 7 8 9 10; do curl -fs http://127.0.0.1:11434/api/version >/dev/null && break; sleep 2; done
for model in $MODELS; do ollama pull "$model"; done
ollama list
