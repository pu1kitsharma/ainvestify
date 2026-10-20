# D3 training pipeline: Phase A local proof (20 October 2026)

Status: **plumbing proven end to end on a 0.5B model with fictional tasks. No quality is claimed.**
Cost: zero GPU spend; one authorised free download (290 MB). No hosted API, no cloud, no private
data, no database or service touched, no commit.

## What was built (all offline-tested: `.venv/bin/python -m pytest tests/envs tests/training -q` -> 74 passed)

| File | Purpose |
|---|---|
| `training/real_training.py` | One real round: sample via injected OpenAI-compatible endpoint -> score with `training.envs` rewards -> top-k distinct per task -> chat SFT JSONL with role tags -> trainer backend -> held-out eval of base *and* adapter -> read-only manifest |
| `training/backends.py` | `ChatEndpointSampler` (loopback-only unless `allow_remote`, hosted-API hosts always refused), `MlxLoraBackend` (`python -m mlx_lm lora` in the separate MLX venv + generation worker), `QloraBackend` (shells to `qlora_train.py`) |
| `training/qlora_train.py` | CUDA QLoRA (PEFT + TRL) with per-role adapter directories. Config/dataset/policy code unit-tested without a GPU; `run_training` itself is **unrun** (needs CUDA) |
| `training/envs/splits.py` (extended) | `split_training_rows` (leave-one-deal-out), `assert_deals_unseen`, `mix_private_examples` (upweight by repetition, hard cap 10% of the mix), `adapter_destination_ok` (private-trained adapters only under `runtime_qualification/` or `evals/agentic_banker/private/`, never `models/adapters`; symlinks resolved) |
| `training/memorisation_probe.py` | Verbatim-prefix completion rate, adapter vs base, configurable gate (`max_adapter_rate` 0.05, `max_excess_over_base` 0.02); report stores secret hashes only |
| `training/chat_data.py`, `mlx_infer.py`, `synthetic_tasks.py` | Role-tagged chat format (`[ROLE:author|qc|md_reviewer]`), MLX generation worker, fictional E4 tasks |
| `scripts/train_dryrun.py` | The dry run below |

Enforced in code and tests: answer keys never reach the sampler; zero-reward or unsupported-check samples are never
selected, even at threshold 0; malformed *model* output scores 0 instead of crashing the round (found in the first live
run, see below); a deal trained on can't be evaluated; private rows need `private_training_approved`; a round touching
private rows refuses a non-private output path; manifest written exclusively then chmod 0400; role tag of every dataset
row must equal the adapter role.

## Dry run

- Hardware: MacBook, Apple silicon, 16 GB. Ollama had no model loaded (waited for D1's model to unload first; sampling
  used `mlx_lm.server` on 127.0.0.1:8089, an OpenAI-compatible endpoint, not Ollama).
- Base: `mlx-community/Qwen2.5-0.5B-Instruct-4bit`, revision `a5339a4131f135d0fdc6a5c8b5bbed2753bbe0f3`,
  289,601,064 bytes, https://huggingface.co/mlx-community/Qwen2.5-0.5B-Instruct-4bit (`evidence/base_model_manifest.json`;
  weights under ignored `runtime_qualification/agentic_banker/dryrun/base/`). mlx-lm 0.32.0 in `runtime_qualification/finetune/venv`.
- Tasks: 20 fictional training deals + 2 valid + 2 test (public-style), plus one fictional "private" training deal and one
  fictional private held-out deal (`fictional-private-sigma`, excluded from training by leave-one-deal-out). Each task: copy
  the `[flag:<id>]` tags from a sentence into a JSON list. They are designed to be copyable; they test the pipeline, not banking.
- Round `round-001` (`evidence/round-001-manifest.json`): 210 samples at temperature 0.6 (mean reward 0.541) -> 14 selected
  (reward 1.0, top-2 distinct per task) -> train set 13 public + 1 private (private share 7.1%, cap 10%, upweight x3 limited by
  cap) -> LoRA r=8, 8 layers, 30 iters, lr 5e-5, 0.297% trainable params (1.466M) -> adapter 5.9 MB (`adapters.safetensors`,
  11 MB dir) -> held-out eval on 5 cases (4 public valid/test + 1 held-out private deal): **base 0.557, adapter 1.000**.
  This is 5 copyable fictional cases, one seed, not evidence of skill; `valid.jsonl` overlaps train (copy of a training row) so
  its loss is a plumbing signal only.
- Adapter verified: loaded through `mlx_lm.load(adapter_path=...)` and generated valid JSON for held-out prompts (0 malformed).
- Time: sampling+score ~35 s; training 5.9 s (30 iters, ~340 tok/s); whole round 62 s; round + control 74 s. Peak child RSS
  559 MB (largest MLX process; the model is tiny, this says nothing about 9B memory, which already OOMs on this Mac).
- Memorisation probe: gate run inside the round on two invented canaries absent from training: base 0/2, adapter 0/2, pass.
  **Positive control** (separate adapter trained 60 iters on one repeated canary line, `evidence/probe-positive-control.json`):
  base 0%, adapter 50% (the seen secret reproduced verbatim, the unseen one not) -> gate fails as it should. So the probe can
  detect verbatim memorisation; its sensitivity on a real private-trained 32B adapter is untested.
- Failures kept, not hidden: first attempt (ignored dir `private-attempt1-collapsed/`): the 0.5B never reached reward 1.0 on the
  harder first task design, then with a looser one only 1 example survived; 40 iters at lr 2e-4 on that single example collapsed the model into
  repetition (held-out 0.0 vs base 0.29). A scorer `ValueError` on malformed model observations crashed the second attempt before
  the fix in `model_prediction`. Task copyability was changed to give the tiny model a nonzero hit rate; that is a task
  design choice, not a model improvement.

## Exact commands

```
# one-time: base download (authorised once, free)
runtime_qualification/finetune/venv/bin/python -c "from huggingface_hub import snapshot_download as s; s('mlx-community/Qwen2.5-0.5B-Instruct-4bit', revision='a5339a4131f135d0fdc6a5c8b5bbed2753bbe0f3', local_dir='runtime_qualification/agentic_banker/dryrun/base')"
# full round + positive control (needs: no Ollama model loaded; ~75 s)
.venv/bin/python scripts/train_dryrun.py
# what it runs underneath
runtime_qualification/finetune/venv/bin/python -m mlx_lm server --model <base> --host 127.0.0.1 --port 8089
runtime_qualification/finetune/venv/bin/python -m mlx_lm lora --model <base> --train --data <round>/data --adapter-path <round>/adapter --iters 30 --batch-size 1 --num-layers 8 --learning-rate 5e-05 --max-seq-length 512 --mask-prompt --grad-checkpoint -c <round>/data/mlx_lora.yaml
# standalone probe on a real adapter (private facts file: JSON list of {id,prefix,secret})
.venv/bin/python -m training.memorisation_probe --facts <private facts.json> --base-model <base> --adapter <adapter> --mlx-python <mlx venv python> --output <new report.json>
# offline tests
.venv/bin/python -m pytest tests/envs tests/training -q
```

## What this proves / does not prove

Proves: sampling from an OpenAI-compatible endpoint, scoring, filtering, role-tagged SFT export, a real MLX LoRA
update, adapter load+generate, base-vs-adapter held-out scoring, leave-one-deal-out and 10% private cap logic, private-path
enforcement, immutable manifest with hashes, and a memorisation probe with a working positive control.

Does **not** prove: any banking competence; that expert iteration improves a capable model; statistical significance (5
held-out cases, one seed); the CUDA/QLoRA path (never executed); behaviour of 9B/32B models; GGUF conversion/Ollama serving
of adapters (unverified, see `models/README.md`); that rewards are semantically correct (E1-E7 rewards check supplied
observations only); that the probe catches paraphrase leakage.

## Delta to run on a CUDA host (QLoRA, e.g. 32B)

1. Env: `pip install torch transformers peft trl bitsandbytes datasets accelerate` (not installed here; `.venv` is Python 3.9).
2. Sampler: point `ChatEndpointSampler` at an operator-owned vLLM server (`allow_remote=True`; hosted vendor APIs
   stay refused) serving the base; budget samples per case far above this dry run's 10.
3. Backend: `QloraBackend(python=<gpu python>)` instead of `MlxLoraBackend`; pass `role=` (done automatically) so author, QC and
   MD-reviewer adapters train on separate datasets into `<out>/<role>/`. First check config on any machine:
   `python training/qlora_train.py --base-model <repo> --data-dir <dir> --output-dir <dir> --role qc --print-config`.
4. Generator for held-out/probe: `make_generator` currently wraps MLX; supply a vLLM (`--enable-lora`) or PEFT-based generator with
   the same `fn(prompts)->texts` signature (not written; needs a GPU to validate).
5. Pin the base revision in `models/base_model.json`-style manifest; pass it as `base_info`. `qlora_train.py` takes `--revision`.
6. Private data: use `--private`/private rows and an output root under `runtime_qualification/` or `evals/agentic_banker/private/`.
   Never `models/adapters`. Public-only adapters may go to Git LFS only after held-out win + independent review.
7. Unverified details to expect to adjust on first GPU run: TRL arg names (`completion_only_loss`, `eval_strategy`) vary by version;
   target-module list for the chosen architecture; sequence length/memory on the actual GPU.
