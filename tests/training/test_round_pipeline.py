import json
from pathlib import Path

import pytest

from training import chat_data
from training.backends import ChatEndpointSampler, MlxLoraBackend, QloraBackend, check_endpoint
from training.memorisation_probe import run_probe, verbatim_hit
from training.real_training import run_round, select_top_k
from training.synthetic_tasks import synthetic_rows


PHRASES = {'thousands and millions': 'units', 'different comparator': 'comparator', '53-week': 'period',
           'another currency': 'currency', 'rounding': 'rounding', 'divested unit': 'scope'}


def oracle(messages):
    """Fake endpoint that reads the prompt (never an answer key) and answers correctly."""
    text = json.loads(messages[1]['content'])['source_text']
    flags = sorted(v for k, v in PHRASES.items() if k in text)
    return json.dumps({'observations': {'flags': {'status': 'observed', 'value': flags}}})


class FakeBackend:
    name = 'fake_trainer'

    def __init__(self):
        self.calls = []

    def train(self, base_model, data_dir, adapter_dir, hyper, log_path):
        self.calls.append(Path(data_dir))
        Path(adapter_dir).mkdir(parents=True)
        (Path(adapter_dir) / 'adapters.safetensors').write_bytes(b'fake-weights')
        Path(log_path).write_text('ok')
        return {'backend': self.name, 'hyper': hyper}


def make_generator(base, adapter):
    return lambda prompts: [oracle(p) if adapter else '{}' for p in prompts]


def run(tmp_path, root=None, **kw):
    public, private = synthetic_rows()
    args = dict(round_id='r1', public_rows=public, output_root=root or tmp_path / 'out', sampler=oracle,
                backend=FakeBackend(), base_model_dir=tmp_path, base_info={'declared': 'fake'},
                make_generator=make_generator, repo_root=tmp_path, config={'samples_per_case': 2})
    args.update(kw)
    return run_round(**args), args


def test_public_round_produces_immutable_manifest_and_beats_fake_base(tmp_path):
    manifest, args = run(tmp_path)
    assert manifest['quality_claim'] == 'none' and manifest['investor_acceptance'] is False
    assert manifest['weights_trained'] and manifest['adapter_verified']
    assert manifest['heldout']['adapter_beats_base'] and manifest['memorisation_probe'] == 'unrun'
    assert manifest['reward_stats']['selected'] == 8  # top-k distinct, 8 identical-per-case answers dedupe to 1 each
    path = tmp_path / 'out/r1/manifest.json'
    assert (path.stat().st_mode & 0o777) == 0o400
    train_rows = chat_data.read_jsonl(tmp_path / 'out/r1/data/train.jsonl')
    assert chat_data.validate_dataset(train_rows, 'author') == 8
    with pytest.raises(FileExistsError):
        run(tmp_path)


def test_answer_key_never_reaches_sampler(tmp_path):
    seen = []
    def spy(messages):
        seen.append(json.dumps(messages))
        return oracle(messages)
    run(tmp_path, sampler=spy)
    assert seen and not any('expected' in s or 'answer_key' in s for s in seen)


def test_zero_reward_samples_never_selected_even_at_threshold_zero():
    rec = {'case_id': 'c', 'text': 't', 'reward': {'reward': 0.0, 'checks': {'x': {'status': 'matched'}}}}
    assert select_top_k([rec], 2, 0.0) == []
    rec2 = {'case_id': 'c', 'text': 't', 'reward': {'reward': 0.5, 'checks': {'x': {'status': 'unsupported'}}}}
    assert select_top_k([rec2], 2, 0.0) == []


def test_all_wrong_samples_fail_closed_before_training(tmp_path):
    backend = FakeBackend()
    with pytest.raises(ValueError, match='nothing to train'):
        run(tmp_path, sampler=lambda m: 'not json', backend=backend)
    assert not backend.calls
    assert (tmp_path / 'out/r1/failure.json').exists()


def test_private_round_requires_ignored_private_path_and_caps_share(tmp_path):
    public, private = synthetic_rows(n_train=8)
    private_rows = [dict(private[0]), dict(private[1])]
    with pytest.raises(ValueError, match='ignored private'):
        run(tmp_path, root=tmp_path / 'models/adapters', private_rows=private_rows)
    manifest, _ = run(tmp_path, root=tmp_path / 'runtime_qualification/agentic_banker/dryrun', private_rows=private_rows,
                      config={'samples_per_case': 2, 'private_upweight': 5})
    mix = manifest['data_provenance']['mix']
    assert mix['private_used'] / (mix['public'] + mix['private_used']) <= 0.10
    assert manifest['adapter']['trained_on_private'] is True
    assert 'fictional-private-omega' in manifest['data_provenance']['trained_on_deals']


def test_leave_one_deal_out_private_deal_is_evaluated_not_trained(tmp_path):
    public, private = synthetic_rows()
    manifest, _ = run(tmp_path, root=tmp_path / 'runtime_qualification/x', private_rows=private,
                      held_out_deals=['fictional-private-sigma'])
    prov = manifest['data_provenance']
    assert 'fictional-private-sigma' not in prov['trained_on_deals']
    assert 'fictional-private-sigma' in prov['held_out_deals']
    assert prov['excluded_private_cases'] == ['syn-private-heldout']
    assert manifest['heldout']['cases'] == 5


def test_trained_deal_cannot_be_scored(tmp_path):
    public, private = synthetic_rows()
    public[8]['deal_id'] = private[0]['deal_id']  # a valid-split case of a deal that is also trained on
    with pytest.raises(ValueError, match='trained on deal'):
        run(tmp_path, public_rows=public, root=tmp_path / 'runtime_qualification/x', private_rows=private)


def test_private_rows_need_explicit_rights(tmp_path):
    public, private = synthetic_rows()
    private[0]['rights_status'] = 'public_training_approved'
    with pytest.raises(ValueError):
        run(tmp_path, root=tmp_path / 'runtime_qualification/x', private_rows=private)


def test_endpoint_policy_blocks_hosted_and_remote():
    for url in ('https://api.openai.com/v1', 'https://api.anthropic.com', 'http://10.0.0.5:8000/v1', 'ftp://x'):
        with pytest.raises(ValueError):
            check_endpoint(url)
    assert check_endpoint('http://127.0.0.1:11434/v1/') == 'http://127.0.0.1:11434/v1'
    assert check_endpoint('http://10.0.0.5:8000/v1', allow_remote=True)
    with pytest.raises(ValueError):
        check_endpoint('https://api.openai.com/v1', allow_remote=True)


def test_sampler_posts_chat_completion_and_parses_reply():
    sent = {}
    def post(url, payload):
        sent.update(url=url, **payload)
        return {'choices': [{'message': {'content': 'hi'}}]}
    s = ChatEndpointSampler('http://localhost:8080/v1', 'm', post=post, temperature=0.5)
    assert s([{'role': 'user', 'content': 'x'}]) == 'hi'
    assert sent['url'].endswith('/v1/chat/completions') and sent['temperature'] == 0.5
    bad = ChatEndpointSampler('http://localhost:1/v1', 'm', post=lambda u, p: {})
    with pytest.raises(ValueError):
        bad([])


def test_mlx_and_qlora_command_lines(tmp_path):
    cmd, h = MlxLoraBackend('/venv/bin/python').train_command('base', 'data', 'ad', {'iters': 7}, 'c.yaml')
    assert cmd[:5] == ['/venv/bin/python', '-m', 'mlx_lm', 'lora', '--model']
    assert '--train' in cmd and cmd[cmd.index('--iters') + 1] == '7' and '--mask-prompt' in cmd
    q = QloraBackend('py').train_command('b', 'd', 'o', {'lora_r': 32}, 'qc', True)
    assert q[1].endswith('qlora_train.py') and '--private' in q and q[q.index('--role') + 1] == 'qc'
    assert q[q.index('--lora-r') + 1] == '32'


def test_role_tags_separate_datasets():
    ex = chat_data.to_example('qc', {'a': 1}, 'resp')
    assert chat_data.example_role(ex) == 'qc'
    chat_data.validate_dataset([ex], 'qc')
    with pytest.raises(ValueError):
        chat_data.validate_dataset([ex], 'author')
    with pytest.raises(ValueError):
        chat_data.build_prompt('ceo', {})


def test_parse_prediction_never_repairs():
    p = chat_data.parse_prediction('noise {"observations": {"flags": 1}} tail', 'c', 'E4')
    assert p['observations'] == {'flags': 1}
    assert chat_data.parse_prediction('nothing', 'c', 'E4')['observations'] == {}
    assert chat_data.parse_prediction('{"observations": 5}', 'c', 'E4')['observations'] == {}


def test_memorisation_probe_detects_leak_and_charges_only_excess_over_base():
    facts = [{'id': 'f1', 'prefix': 'ARR was ', 'secret': '7,318,442'},
             {'id': 'f2', 'prefix': 'Cash was ', 'secret': '4,906,157'}]
    leak = lambda prompts: ['7318442 dollars', '4,906,157']
    clean = lambda prompts: ['about 3 million', 'unknown']
    bad = run_probe(facts, clean, leak)
    assert bad['base_rate'] == 0 and bad['adapter_rate'] == 1 and not bad['passed']
    assert '7318442' not in json.dumps(bad['per_fact']) and '7,318,442' not in json.dumps(bad['per_fact'])
    assert run_probe(facts, clean, clean)['passed']
    # base already produces it (public knowledge): adapter at the same rate passes only if under abs gate
    assert not run_probe(facts, leak, leak)['passed']
    assert run_probe(facts, leak, leak, gate={'max_adapter_rate': 1.0, 'max_excess_over_base': 0.0})['passed']


def test_verbatim_hit_rejects_longer_number_and_secret_in_prefix():
    assert verbatim_hit(' 7,318,442 USD', '7318442')
    assert not verbatim_hit('73184420', '7318442')
    assert not verbatim_hit('7318442.5', '7318442')
    with pytest.raises(ValueError):
        run_probe([{'id': 'a', 'prefix': 'x 123 ', 'secret': '123'}], lambda p: [''], lambda p: [''])


def test_malformed_model_observations_score_zero_instead_of_crashing_round(tmp_path):
    def sloppy(messages):
        if 'thousands and millions' in messages[1]['content']:
            return '{"observations": {"flags": {"status": "observed|missing", "value": ["units"]}}}'
        return oracle(messages)
    manifest, _ = run(tmp_path, sampler=sloppy)
    assert manifest['reward_stats']['selected'] >= 1
    assert json.loads((tmp_path / 'out/r1/heldout_base.json').read_text())['malformed_outputs'] >= 0
