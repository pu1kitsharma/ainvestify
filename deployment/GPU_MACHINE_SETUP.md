# GPU machine setup (Linux, NVIDIA): step by step

Applies to a local GPU box or a GCP VM created by `deploy/gcp/` (the VM's startup script already does steps 6-7
for the serving side). **Nothing below has been run on a GPU machine.** It was written and its helper code unit-tested
on a macOS laptop with fakes. Section 12 lists exactly what is unverified. No hosted/cloud model API is used anywhere;
the only network use is the one-time weight download (step 5) and package installs.

Conventions: repo at `~/deal_document`, venvs under `~/venvs/`, weights under `/data/weights` (any disk with space).
Two virtualenvs on purpose: **train** (torch + PEFT/TRL) and **serve** (vLLM brings its own pinned torch).

## 1. Drivers and CUDA check

```bash
nvidia-smi                                  # must list the GPU; note "CUDA Version" (max the driver supports)
lsb_release -a; python3 --version           # Ubuntu 22.04/24.04 and Python 3.10-3.12 expected
df -h /data                                 # see section 9 for sizes; 200 GB free is a safe floor for 32B
```

If `nvidia-smi` is missing: install the vendor driver (Ubuntu: `sudo ubuntu-drivers install`, reboot). You do **not**
need the full CUDA toolkit for torch/vLLM wheels, only a driver new enough for the wheel's CUDA runtime
(cu124 wheels want a roughly >= 550 driver; confirm in the PyTorch install matrix). GCP Deep Learning VM images
ship driver + CUDA already.

## 2. OS packages (sandbox + office recalculation)

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv python3-dev build-essential bubblewrap libreoffice-calc
bwrap --version && which soffice            # both needed for office recalculation; absent => results are UNRUN, never "pass"
```

Optional override: `export LIBREOFFICE_BINARY=/opt/libreoffice25.2/program/soffice`. If bubblewrap fails inside a
container/VM with "No permissions to create new namespace", enable unprivileged user namespaces
(`sudo sysctl kernel.unprivileged_userns_clone=1` on Debian-like kernels, or `kernel.apparmor_restrict_unprivileged_userns=0`
on Ubuntu 24.04) or run the office steps elsewhere; the code will keep reporting UNRUN rather than run unsandboxed.

## 3. Repo and training venv

```bash
git clone <your repo> ~/deal_document && cd ~/deal_document
python3 -m venv ~/venvs/train && source ~/venvs/train/bin/activate
pip install -U pip wheel
pip install "torch>=2.4,<2.9" --index-url https://download.pytorch.org/whl/cu124   # pick the cuXYZ your driver supports
pip install -r requirements-gpu.txt
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"   # expect True
```

Sanity (no model download): `python training/qlora_train.py --base-model dummy --data-dir <dir with train.jsonl> --output-dir /tmp/x --role author --print-config`.

## 4. Serving venv (vLLM)

```bash
python3 -m venv ~/venvs/serve && source ~/venvs/serve/bin/activate
pip install -U pip && pip install "vllm==0.10.2"        # same pin as deploy/gcp/vllm_config.env; installs its own torch
vllm --version
```

## 5. Model weights

Online (once; this is the only intended internet step):

```bash
source ~/venvs/train/bin/activate
export HF_HOME=/data/hf-cache
huggingface-cli login                                   # only for gated repos; Qwen repos are not gated
python - <<'PY'
from huggingface_hub import snapshot_download
# Pin the revision (commit SHA from the model page) so the base is reproducible; "main" is NOT a pin.
snapshot_download("Qwen/Qwen3-32B", revision="<COMMIT_SHA>", local_dir="/data/weights/base")
PY
sha256sum /data/weights/base/*.safetensors > /data/weights/base.sha256     # keep with the manifest
```

Write `/data/weights/base_model_manifest.json` (`{"repo": "...", "revision": "<COMMIT_SHA>", "license": "..."}`);
`training.gpu_generate round` records it in the round manifest. Which base to use is decided by the bake-off, not here.
Check the model licence yourself before any commercial use; this repo does not assert one.

Offline-bundle option (no internet on the GPU host): on a connected machine run the same `snapshot_download` to a
folder, record `sha256sum`, copy with `rsync`/disk to `/data/weights/base`, verify the checksums on arrival, and set
`export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` on the GPU host. Pip needs the same treatment:
`pip download -r requirements-gpu.txt -d wheelhouse/` on the connected machine (match Python version and CUDA tag), then
`pip install --no-index --find-links wheelhouse -r requirements-gpu.txt`.

## 6. Launch vLLM on a private interface with a token

The endpoint policy admits only RFC1918/ULA addresses (or names in `SELFHOSTED_ALLOWED_HOSTS`). Never bind `0.0.0.0` on a
host with a public interface; bind the private IP.

```bash
umask 077
mkdir -p ~/secrets && head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > ~/secrets/vllm-token   # >=16 chars, no whitespace
PRIVATE_IP=$(hostname -I | awk '{print $1}')                    # confirm it is 10.x / 172.16-31.x / 192.168.x
export VLLM_API_KEY="$(cat ~/secrets/vllm-token)"               # read from the environment, not argv
export VLLM_ALLOW_RUNTIME_LORA_UPDATING=True                    # lets training.gpu_generate load new adapters
source ~/venvs/serve/bin/activate
vllm serve /data/weights/base --host "$PRIVATE_IP" --port 8000 --served-model-name banker-base \
     --max-model-len 32768 --gpu-memory-utilization 0.90 \
     --enable-lora --max-loras 4 --max-lora-rank 64 \
     --enable-auto-tool-choice --tool-call-parser hermes        # tool calling for the agent runtime (Qwen: hermes)
```

(`--tool-call-parser` name and the runtime-LoRA env var are from vLLM docs as remembered; confirm with `vllm serve --help`
and the 0.10.2 docs.) Client side environment (same host or another private-network host):

```bash
export SELFHOSTED_BASE_URL="http://$PRIVATE_IP:8000"
export SELFHOSTED_TOKEN_FILE=~/secrets/vllm-token               # preferred over SELFHOSTED_TOKEN
# only if you address it by an internal DNS name instead of the literal IP:  export SELFHOSTED_ALLOWED_HOSTS=gpu.internal
```

On the GCP VM, `deploy/gcp/startup-script.sh` creates the token from Secret Manager and the systemd unit; the unit does not
currently set `VLLM_ALLOW_RUNTIME_LORA_UPDATING` or `--enable-auto-tool-choice`, so add them (or list adapters via
`LORA_MODULES` and pass `adapter_names`).

## 7. Pre-flight and smoke tests

```bash
source ~/venvs/train/bin/activate && cd ~/deal_document
python scripts/gpu_preflight.py --mode local --expect-model banker-base --min-disk-gb 200
#   gcp mode adds: --mode gcp --run-plan deployment/<filled plan>.md --ledger <path to ledger sqlite>
```

It is read-only: nvidia-smi, torch CUDA, package list, free disk, bwrap + LibreOffice presence, token present (value never
printed), `GET /v1/models` on the private endpoint with expected names, and in gcp mode the run plan + ledger. Exit code 1
on any FAIL. Then, offline tests that need no GPU (should pass on the GPU box too):

```bash
python -m pytest tests/selfhosted tests/gpu_ready tests/runtime tests/tools tests/gpu tests/inference tests/delivery tests/training -q
```

One-token smoke (cheap; proves auth, route, receipts) using the real client:

```bash
python - <<'PY'
from agents.inference.endpoint_policy import resolve_selfhosted_route
from agents.inference.selfhosted_client import SelfHostedClient
c = SelfHostedClient(resolve_selfhosted_route('selfhosted:banker-base'))
print(c.list_models()); print(repr(c.chat([{'role':'user','content':'Reply with the word ok.'}], max_tokens=8, allow_length=True)))
PY
```

## 8. First bake-off, then first training round (existing code paths)

Bake-off (banker harness over the self-hosted route; refuses to call the model without `--run`):

```bash
python -m training.gpu_generate bakeoff --case <private case json> --output evals/agentic_banker/private/bakeoff-001 \
       --model banker-base --mode blocks --profile diagnostic            # validates only
python -m training.gpu_generate bakeoff ... --run                         # runs inference on the private endpoint
python scripts/evaluate_agentic_banker.py --predictions ... --answer-key ... --output <new path>   # scoring, unchanged
```

(`scripts/evaluate_local_banker.py` cannot be pointed at this route: it accepts loopback endpoints only and sends no token.)
Receipts (raw request/response bytes + hashes) land under each run directory exactly as with Ollama.

First training round. Training needs the GPU memory vLLM is holding, so pass stop/start commands (or serve with
`--gpu-memory-utilization 0.40` and a model small enough to share the card; not possible for 32B on one 80 GB card):

```bash
python -m training.gpu_generate round --round-id round-001 --public-rows <rows.jsonl> [--private-rows <p.jsonl>] \
   --out evals/agentic_banker/private/rounds --base-dir /data/weights/base --base-manifest /data/weights/base_model_manifest.json \
   --base-name banker-base --role author --samples-per-case 8 --hyper '{"lora_r":16,"epochs":2,"learning_rate":1e-4}' \
   --vllm-stop-cmd "sudo systemctl stop vllm" --vllm-start-cmd "sudo systemctl start vllm"
```

Sampling and held-out evaluation go through vLLM; adapters are loaded by name through `/v1/load_lora_adapter` (adapter dir is
`<out>/<round>/adapter/<role>/`). The memorisation probe: add `--facts <private facts json>` to the round, or run it alone:
`python -m training.gpu_generate probe --facts F --base-name banker-base --adapter-name <served lora name> --output <new path>`.
Private-trained adapters must stay under an ignored private root (enforced by `adapter_destination_ok`). Rows must have the
same shape as `training.synthetic_tasks.synthetic_rows()` (the first round on GPU should be that synthetic set again to prove
plumbing before spending time on real data). `quality_claim` stays `none`.

## 9. Memory sizing (rough, unmeasured; weights = params x bytes/param, plus allowances)

Serving = weights + ~15-25% for KV cache/runtime at 16-32k context (long contexts and several LoRAs need more).
QLoRA training = 4-bit weights + LoRA/optimizer + activations with gradient checkpointing at seq 4096, batch 1.
Parameter counts: 7B ~7.6B, 14B ~14.8B, 32B ~32.8B (Qwen-family sizes).

| Model | Precision | Weights | Serve (approx) | QLoRA train (approx) | 24 GB | 40 GB | 80 GB |
|---|---|---|---|---|---|---|---|
| 7B | 4-bit (AWQ/GPTQ/NF4) | ~4.5 GB | ~6 GB | ~10-14 GB | serve + train | serve + train | serve + train |
| 7B | 8-bit (FP8/INT8) | ~8 GB | ~10 GB | n/a (LoRA-8bit untested) | serve | serve | serve |
| 7B | 16-bit (bf16) | ~15 GB | ~19 GB | ~24+ GB (plain LoRA) | serve (tight) | serve + LoRA | serve + LoRA |
| 14B | 4-bit | ~9 GB | ~11 GB | ~16-22 GB | serve; train tight | serve + train | serve + train |
| 14B | 8-bit | ~15 GB | ~19 GB | n/a | serve (tight) | serve | serve |
| 14B | 16-bit | ~30 GB | ~36 GB | ~40+ GB | no | serve (tight) | serve + LoRA |
| 32B | 4-bit | ~17-19 GB | ~22 GB | ~26-34 GB | serve (very tight, short ctx) | serve + train (tight) | serve + train |
| 32B | 8-bit | ~33 GB | ~40 GB | n/a | no | serve (very tight) | serve |
| 32B | 16-bit | ~66 GB | ~78 GB | n/a | no | no | serve (tight, short ctx) |

Training and serving at once on one card do not fit for 32B; use `--vllm-stop-cmd/--vllm-start-cmd`. Treat every number as a
planning estimate to be replaced by `nvidia-smi` readings from the first real run; record them in the round manifest notes.

## 10. Bring-down

Stop vLLM (`sudo systemctl stop vllm` or Ctrl-C), delete `~/secrets/vllm-token` if the host is shared, and on GCP stop the VM
via `delivery/gpu_lifecycle.py` (never leave a created VM running; see `deploy/gcp/CHECKLIST.md`).

## 11. Linux portability changes in this repo

| Area | Behaviour on Linux |
|---|---|
| `delivery/isolation.py` | `bwrap` backend: `--unshare-all` (no network), `--die-with-parent`, `--new-session`, `--clearenv`, read-only binds of `/usr`, lib dirs, minimal `/etc`, interpreter prefixes, `delivery/ security/ scripts/`; tmpfs `/tmp`; the job dir is the only writable bind. No `bwrap` => `RuntimeError('private_process_isolation_unavailable')`, never an unsandboxed run. `local_model=True` (TCP to Ollama inside the sandbox) is **refused** on Linux. |
| `delivery/libreoffice.py`, `agents/tools/recalc.py` | Binary from `LIBREOFFICE_BINARY`, else `soffice`/`libreoffice` on PATH or common install paths; unusable explicit override is not silently replaced. Missing sandbox or office => `UNRUN`. |
| Still macOS-only (fail closed, not ported) | `delivery/document_ocr.py` + `scripts/private_vision_ocr.swift` (Apple Vision OCR; needs `swiftc`), `scripts/claude_code_local.py` (sandbox-exec reviewer launcher), `delivery/rendering.py` / `delivery/worker.py` font paths under `/Applications/LibreOffice.app` (fall back when absent; Linux rendering fonts come from system DejaVu if the code finds them, unverified), `training/backends.MlxLoraBackend` and `training/mlx_infer.py` (MLX; replaced by QLoRA + vLLM on GPU), `scripts/create_local_dev_user.py`, `scripts/qualify_private_office_isolation.py` and `scripts/qualify_renderers.py` (use `/private/tmp`). OCR consumers must treat a missing OCR engine as unavailable; a Linux OCR path (e.g. a separately qualified Tesseract) is not built. |

## 12. Not verifiable on the dev Mac (unverified until run on a real GPU box)

- Every command in sections 1-8: driver/CUDA versions, pip resolution of `requirements-gpu.txt`, torch/bitsandbytes/TRL
  compatibility (`SFTConfig(completion_only_loss=...)` names vary by TRL version), vLLM 0.10.2 flags, tool-call parser name,
  runtime LoRA loading (`/v1/load_lora_adapter`, its request fields and whether it requires the adapter path on the server's disk).
- Real vLLM response shapes (finish_reason values with tool calls, usage fields, model-name echo for LoRA adapters). The client
  is tested only against a stdlib fake that follows the OpenAI schema as understood.
- `bwrap` itself: the argv builder is tested; actual namespace creation, whether LibreOffice starts under that bind set
  (it may need more of `/etc`, `/var`, fonts or `/proc` entries), and fonts for PDF rendering. Expect to iterate the bind list
  on first run, adding only literal needed paths.
- `PeftGenerator` and `qlora_train.run_training` (never executed anywhere); `bitsandbytes` 4-bit loading.
- Memory table figures and throughput; any model-quality result. The bake-off on a real GPU is the first fair measurement.
