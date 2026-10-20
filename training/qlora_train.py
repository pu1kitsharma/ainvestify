"""CUDA QLoRA SFT with PEFT + TRL, one adapter per role (author / qc / md_reviewer).

Cannot run on the 16 GB Mac (needs CUDA + bitsandbytes). The configuration, dataset
and storage-policy code below is pure Python and unit-tested without a GPU; heavy
imports happen only inside `run_training`.

    python training/qlora_train.py --base-model Qwen/Qwen2.5-32B-Instruct \
        --data-dir <dir with train.jsonl, valid.jsonl> --output-dir <dir> --role author

Role adapters: the dataset's system tag `[ROLE:<role>]` must equal --role, and the
output goes to <output-dir>/<role>/, so author, QC and MD-reviewer adapters never
share files or data. `--private` marks data derived from private deals: the output
must then be under an ignored private root (training.envs.adapter_destination_ok),
never models/adapters (Git LFS).

Requires: torch, transformers, peft, trl, bitsandbytes, datasets, accelerate.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from training.chat_data import ROLES, read_jsonl, validate_dataset  # noqa: E402
from training.envs.splits import adapter_destination_ok  # noqa: E402

# Attention + MLP projections: valid for Qwen / Llama style decoders.
DEFAULT_TARGET_MODULES = ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']


def build_parser():
    p = argparse.ArgumentParser(description='QLoRA role-adapter training (CUDA host)')
    p.add_argument('--base-model', required=True, help='HF repo id or local path (pin a revision with --revision)')
    p.add_argument('--revision', default=None)
    p.add_argument('--data-dir', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--role', required=True, choices=sorted(ROLES))
    p.add_argument('--private', action='store_true', help='data derived from private deals')
    p.add_argument('--lora-r', type=int, default=16)
    p.add_argument('--lora-alpha', type=int, default=32)
    p.add_argument('--lora-dropout', type=float, default=0.05)
    p.add_argument('--target-modules', nargs='+', default=DEFAULT_TARGET_MODULES)
    p.add_argument('--no-4bit', action='store_true', help='plain LoRA in bf16 (small models only)')
    p.add_argument('--max-seq-length', type=int, default=4096)
    p.add_argument('--epochs', type=float, default=2.0)
    p.add_argument('--learning-rate', type=float, default=1e-4)
    p.add_argument('--batch-size', type=int, default=1)
    p.add_argument('--grad-accum', type=int, default=16)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--repo-root', default=str(REPO))
    p.add_argument('--print-config', action='store_true', help='validate everything, print config, exit')
    return p


def resolve_config(args):
    """Pure validation + resolution. Raises ValueError on any policy violation."""
    for name, lo in (('lora_r', 1), ('lora_alpha', 1), ('max_seq_length', 64), ('batch_size', 1), ('grad_accum', 1)):
        if getattr(args, name) < lo:
            raise ValueError('%s must be >= %d' % (name, lo))
    if not 0 <= args.lora_dropout < 1 or args.epochs <= 0 or args.learning_rate <= 0:
        raise ValueError('Invalid dropout/epochs/learning rate')
    data = Path(args.data_dir)
    train, valid = read_jsonl(data / 'train.jsonl'), read_jsonl(data / 'valid.jsonl') if (data / 'valid.jsonl').exists() else []
    validate_dataset(train, args.role)
    if valid:
        validate_dataset(valid, args.role)
    # One directory per role keeps author / QC / MD-reviewer adapters separate.
    out = adapter_destination_ok(Path(args.output_dir) / args.role, trained_on_private=args.private,
                                 repo_root=args.repo_root)
    return {
        'role': args.role, 'private': bool(args.private), 'base_model': args.base_model, 'revision': args.revision,
        'output_dir': str(out), 'quantization': None if args.no_4bit else
        {'load_in_4bit': True, 'bnb_4bit_quant_type': 'nf4', 'bnb_4bit_use_double_quant': True,
         'bnb_4bit_compute_dtype': 'bfloat16'},
        'lora': {'r': args.lora_r, 'lora_alpha': args.lora_alpha, 'lora_dropout': args.lora_dropout,
                 'target_modules': list(args.target_modules), 'bias': 'none', 'task_type': 'CAUSAL_LM'},
        'sft': {'max_length': args.max_seq_length, 'num_train_epochs': args.epochs, 'learning_rate': args.learning_rate,
                'per_device_train_batch_size': args.batch_size, 'gradient_accumulation_steps': args.grad_accum,
                'seed': args.seed, 'gradient_checkpointing': True, 'bf16': True, 'lr_scheduler_type': 'cosine',
                'warmup_ratio': 0.03, 'logging_steps': 5, 'save_strategy': 'epoch', 'report_to': 'none'},
        'data': {'train_rows': len(train), 'valid_rows': len(valid),
                 'train_sha256': hashlib.sha256((data / 'train.jsonl').read_bytes()).hexdigest()},
    }


def to_prompt_completion(examples):
    """Chat rows -> TRL conversational prompt/completion rows (loss on the completion only)."""
    return [{'prompt': ex['messages'][:-1], 'completion': [ex['messages'][-1]]} for ex in examples]


def run_training(config, data_dir):  # pragma: no cover - needs CUDA stack
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    quant = None
    if config['quantization']:
        q = dict(config['quantization'])
        q['bnb_4bit_compute_dtype'] = getattr(torch, q['bnb_4bit_compute_dtype'])
        quant = BitsAndBytesConfig(**q)
    tok = AutoTokenizer.from_pretrained(config['base_model'], revision=config['revision'])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(config['base_model'], revision=config['revision'],
                                                 quantization_config=quant, torch_dtype=torch.bfloat16,
                                                 device_map='auto')
    data = Path(data_dir)
    train = Dataset.from_list(to_prompt_completion(read_jsonl(data / 'train.jsonl')))
    valid_rows = read_jsonl(data / 'valid.jsonl') if (data / 'valid.jsonl').exists() else []
    valid = Dataset.from_list(to_prompt_completion(valid_rows)) if valid_rows else None
    out = Path(config['output_dir'])
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    args = SFTConfig(output_dir=str(out / 'checkpoints'), eval_strategy='epoch' if valid else 'no',
                     completion_only_loss=True, **config['sft'])
    trainer = SFTTrainer(model=model, args=args, train_dataset=train, eval_dataset=valid,
                         processing_class=tok, peft_config=LoraConfig(**config['lora']))
    result = trainer.train()
    trainer.model.save_pretrained(out)  # adapter_model.safetensors + adapter_config.json only
    return {'train_loss': float(result.training_loss), 'steps': int(result.global_step)}


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = resolve_config(args)
    if args.print_config:
        print(json.dumps(config, indent=2, sort_keys=True))
        return 0
    stats = run_training(config, args.data_dir)
    manifest = {'contract': 'qlora-adapter-v1', 'config': config, 'stats': stats, 'quality_claim': 'none'}
    path = Path(config['output_dir']) / 'adapter_manifest.json'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
