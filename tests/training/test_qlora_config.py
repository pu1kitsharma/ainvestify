import json

import pytest

from training import chat_data, qlora_train


def data_dir(tmp_path, role='author'):
    d = tmp_path / 'data'
    d.mkdir(exist_ok=True)
    rows = [chat_data.to_example(role, {'k': i}, '{"observations": {}}') for i in range(3)]
    for name in ('train.jsonl', 'valid.jsonl'):
        (d / name).write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return d


def parse(tmp_path, *extra, role='author'):
    return qlora_train.build_parser().parse_args(
        ['--base-model', 'org/model', '--data-dir', str(data_dir(tmp_path, role)),
         '--output-dir', str(tmp_path / 'out'), '--role', role, '--repo-root', str(tmp_path), *extra])


def test_config_resolves_without_gpu_and_separates_role_directory(tmp_path):
    cfg = qlora_train.resolve_config(parse(tmp_path, '--lora-r', '32'))
    assert cfg['output_dir'].endswith('/out/author') and cfg['lora']['r'] == 32
    assert cfg['quantization']['bnb_4bit_quant_type'] == 'nf4' and cfg['data']['train_rows'] == 3
    assert 'q_proj' in cfg['lora']['target_modules']


def test_role_mismatch_between_data_and_adapter_rejected(tmp_path):
    args = parse(tmp_path, role='author')
    args.role = 'qc'
    with pytest.raises(ValueError):
        qlora_train.resolve_config(args)


def test_private_data_cannot_target_lfs_adapter_path(tmp_path):
    args = parse(tmp_path, '--private')
    args.output_dir = str(tmp_path / 'models/adapters/run1')
    with pytest.raises(ValueError, match='private'):
        qlora_train.resolve_config(args)
    args.output_dir = str(tmp_path / 'runtime_qualification/agentic_banker/private/run1')
    assert qlora_train.resolve_config(args)['private'] is True


def test_prompt_completion_conversion_keeps_loss_on_assistant_only():
    ex = chat_data.to_example('md_reviewer', {'a': 1}, 'done')
    row = qlora_train.to_prompt_completion([ex])[0]
    assert [m['role'] for m in row['prompt']] == ['system', 'user'] and row['completion'][0]['content'] == 'done'


def test_print_config_cli_exits_before_importing_torch(tmp_path, capsys):
    assert qlora_train.main(['--base-model', 'm', '--data-dir', str(data_dir(tmp_path)), '--output-dir',
                             str(tmp_path / 'o'), '--role', 'author', '--repo-root', str(tmp_path), '--print-config']) == 0
    assert json.loads(capsys.readouterr().out)['role'] == 'author'


def test_bad_hyperparameters_rejected(tmp_path):
    for flag, val in (('--lora-r', '0'), ('--epochs', '0'), ('--lora-dropout', '1.5')):
        with pytest.raises(ValueError):
            qlora_train.resolve_config(parse(tmp_path, flag, val))
