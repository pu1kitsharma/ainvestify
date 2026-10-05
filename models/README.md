# Models and fine-tuning artifacts

**What is stored in Git:** only artifacts we author and that are small: LoRA
adapters (tens of MB, via Git LFS under `models/adapters/`) and the manifests
below. **Never committed:** base weights (public, multi-GB, re-downloadable),
merged models, GGUF files, training data derived from private documents.

| Path | In Git | Purpose |
|---|---|---|
| `base_model.json` | yes | Pinned base repo + revision + quantization |
| `adapters/<run-id>/` | yes, LFS | `adapters.safetensors`, `adapter_config.json`, `RUN.json` |
| `base/`, `merged/`, `gguf/`, `data/` | no (ignored) | Local only |

## Reproducible training run (target: a GPU box with >= 24 GB memory)

1. Download the pinned base (see `base_model.json`).
2. Build data: `scripts/build_deck_headline_sft.py` is the template for a task
   dataset (chat-ML text rows, non-thinking Qwen3.5 rendering, the exact system
   prompt the runtime sends). Training data derived from private documents stays
   local and ignored.
3. Train: `python -m mlx_lm lora --model models/base --train --data models/data
   --adapter-path models/adapters/<run-id> --num-layers 16 --batch-size 1
   --max-seq-length 2048 --grad-checkpoint --iters <N>` (MLX, Apple silicon). On
   a CUDA host use PEFT/TRL with the same data and rank. A 16 GB Mac ran out of
   Metal memory with the 9B at 4-bit.
4. Evaluate against a **held-out** split with `scripts/evaluate_deck_headline_mlx.py`
   style scoring, base versus adapter. Record both in `RUN.json` with the
   data hash, base revision, hyperparameters and scores. Do not ship an adapter
   that does not beat the base on held-out data.
5. Serve: llama.cpp (`convert_lora_to_gguf.py`) supports Qwen3.5; load the GGUF
   adapter in Ollama with a Modelfile `ADAPTER` line, or merge and quantize. This
   step is unverified. Register the model name only after the digest is recorded.

## Rules

- Training changes weights only. No code or person writes model output.
- Private-document data and anything derived from it never leaves the private
  environment or enters Git.
- An adapter needs a held-out win over the base and independent review before
  any pipeline role is switched to it.

## Git LFS (for adapters only)

Install once: `brew install git-lfs && git lfs install`. `.gitattributes` routes
`models/adapters/**` through LFS. Adapters are small enough for the free quota;
the 5.6 GB base is deliberately not stored.
