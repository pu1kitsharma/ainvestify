import json
import subprocess
import sys

import pytest

from agents.inference.endpoint_policy import resolve_selfhosted_route
from agents.inference.selfhosted_client import SelfHostedClient
from tests.selfhosted.fake_openai import TOKEN, FakeServer, completion
from training import gpu_generate as gg
from training.memorisation_probe import run_probe

ALLOW = ('localhost',)


def make_client(server, model='banker-base'):
    route = resolve_selfhosted_route('selfhosted:' + model, base_url=server.base_url, token=TOKEN, allowed_hosts=ALLOW)
    return SelfHostedClient(route, allowed_hosts=ALLOW)


def echo_server(server):
    """Answers chat with 'chat:<model>:<last user content>' and raw completions with 'raw:<model>:<prompt>'."""
    def handle(req):
        if req['path'].endswith('/load_lora_adapter'):
            return 200, b'Success'
        body = json.loads(req['body'])
        if req['path'].endswith('/completions') and not req['path'].endswith('chat/completions'):
            text = 'raw:%s:%s' % (body['model'], body['prompt'])
            return 200, json.dumps({'model': body['model'], 'choices': [{'text': text, 'finish_reason': 'length'}]}).encode()
        text = 'chat:%s:%s' % (body['model'], body['messages'][-1]['content'])
        return 200, json.dumps(completion(model=body['model'], content=text, finish='length')).encode()
    server.dynamic = handle


def test_imports_without_torch():
    code = 'import sys; sys.modules["torch"]=None; import training.gpu_generate as g; print(g.PeftGenerator.available())'
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd='.')
    assert out.returncode == 0, out.stderr[-300:]


def test_vllm_generator_order_chat_and_raw_and_length_tolerated():
    with FakeServer() as server:
        echo_server(server)
        gen = gg.vllm_generator(make_client(server), max_tokens=8, workers=4)
        prompts = [[{'role': 'user', 'content': 'm%d' % i}] for i in range(6)] + [{'raw': 'ARR of '}]
        out = gen(prompts)
        assert out[:6] == ['chat:banker-base:m%d' % i for i in range(6)] and out[6] == 'raw:banker-base:ARR of '
        assert {r['path'] for r in server.requests} == {'/v1/chat/completions', '/v1/completions'}
        assert all(r['headers']['Authorization'] == 'Bearer ' + TOKEN for r in server.requests)


def test_adapter_selected_by_model_name_and_autoload():
    with FakeServer() as server:
        echo_server(server)
        factory = gg.make_generator_factory(make_client(server), base_name='banker-base',
                                            adapter_names={'/x/adapter': 'qc_lora'})
        assert factory('/b', None)([{'raw': 'p'}]) == ['raw:banker-base:p']
        assert factory('/b', '/x/adapter')([{'raw': 'p'}]) == ['raw:qc_lora:p']
        auto = gg.make_generator_factory(make_client(server), base_name='banker-base', auto_load_adapters=True)
        name = gg.adapter_model_name('/y/adapter')
        assert auto('/b', '/y/adapter')([{'raw': 'p'}]) == ['raw:%s:p' % name]
        auto('/b', '/y/adapter')
        loads = [r for r in server.requests if r['path'].endswith('load_lora_adapter')]
        assert len(loads) == 1 and json.loads(loads[0]['body'])['lora_name'] == name


def test_factory_validation():
    with pytest.raises(ValueError):
        gg.make_generator_factory(None, base_name='x')
    with pytest.raises(ValueError):
        gg.make_generator_factory(backend='tpu')
    with pytest.raises(ValueError):
        gg.vllm_generator(object(), max_tokens=0)


def test_generator_failure_propagates():
    with FakeServer() as server:
        server.reply(b'', status=503)
        with pytest.raises(Exception) as err:
            gg.vllm_generator(make_client(server))([[{'role': 'user', 'content': 'x'}]])
        assert 'Infra' in type(err.value).__name__


def test_plugs_into_real_training_and_probe_interfaces():
    # heldout_eval and run_probe accept the generator unchanged (existing injected-callable shapes).
    with FakeServer() as server:
        echo_server(server)
        factory = gg.make_generator_factory(make_client(server), base_name='banker-base', adapter_names={'/a': 'lora'}, max_tokens=24)
        facts = [{'id': 'f1', 'prefix': 'Fictional Co closed FY24 with ARR of ', 'secret': '7318'}]
        report = run_probe(facts, factory(None, None), factory(None, '/a'))
        assert report['facts'] == 1 and report['base_rate'] == 0 and '7318' not in json.dumps(report['per_fact'])
        hook = gg.make_probe_hook(factory, facts, base_dir=None)
        assert hook('/a')['passed'] is True


def test_sampler_uses_private_route():
    with FakeServer() as server:
        echo_server(server)
        sampler = gg.sampler_from_client(make_client(server), max_tokens=8)
        assert sampler([{'role': 'user', 'content': 'hello'}]) == 'chat:banker-base:hello'


def test_peft_generator_lazy_and_fake_stack():
    calls = []

    def importer(name):
        calls.append(name)
        raise ImportError(name)
    g = gg.PeftGenerator('/m', importer=importer)
    assert calls == []                      # nothing imported at construction
    with pytest.raises(ImportError):
        g([{'raw': 'x'}])
    assert calls == ['torch']


def test_full_round_with_gpu_generators_against_fake_server(tmp_path):
    from tests.training.test_round_pipeline import FakeBackend, oracle
    from training.real_training import run_round
    from training.synthetic_tasks import synthetic_rows
    public, private = synthetic_rows()
    with FakeServer() as server:
        def handle(req):
            if req['path'].endswith('load_lora_adapter'):
                return 200, b'Success'
            body = json.loads(req['body'])
            sampled = body['temperature'] > 0
            text = oracle(body['messages']) if (sampled or body['model'].startswith('adapter-')) else '{}'
            return 200, json.dumps(completion(model=body['model'], content=text)).encode()
        server.dynamic = handle
        client = make_client(server)
        gen = gg.make_generator_factory(client, base_name='banker-base', auto_load_adapters=True, max_tokens=64)
        manifest = run_round(round_id='g1', public_rows=public, output_root=tmp_path / 'out',
                             sampler=gg.sampler_from_client(client, temperature=0.8), backend=FakeBackend(),
                             base_model_dir=tmp_path, base_info={'declared': 'fake'}, make_generator=gen,
                             repo_root=tmp_path, config={'samples_per_case': 2})
    assert manifest['heldout']['adapter_mean_reward'] > manifest['heldout']['base_mean_reward']
    assert manifest['adapter_verified'] and manifest['quality_claim'] == 'none'


def test_serving_paused_backend_orders_commands_and_restarts_on_failure():
    events = []

    class Inner:
        name = 'cuda_qlora'

        def __init__(self, fail=False): self.fail = fail

        def train(self, *a, **k):
            events.append('train')
            if self.fail:
                raise RuntimeError('oom')
            return {'backend': 'cuda_qlora'}
    ticks = iter(range(100))
    ready = iter([False, True])
    make = lambda inner: gg.ServingPausedBackend(inner, stop_cmd=['stop'], start_cmd=['start'], ready=lambda: next(ready),
                                                 runner=lambda c: events.append(c[0]), sleep=lambda s: events.append('sleep'),
                                                 clock=lambda: next(ticks))
    b = make(Inner())
    assert b.name == 'cuda_qlora' and b.train('b', 'd', 'a', {}, 'log') == {'backend': 'cuda_qlora'}
    assert events == ['stop', 'train', 'start', 'sleep']
    events.clear(); ready = iter([True])
    with pytest.raises(RuntimeError, match='oom'):
        make(Inner(fail=True)).train()
    assert events == ['stop', 'train', 'start']                 # serving restored even when training fails
    with pytest.raises(ValueError):
        gg.ServingPausedBackend(Inner(), stop_cmd='stop', start_cmd=['x'], ready=lambda: True)


def test_adapter_subdir_used_for_qlora_layout(tmp_path):
    with FakeServer() as server:
        echo_server(server)
        (tmp_path / 'author').mkdir()
        factory = gg.make_generator_factory(make_client(server), base_name='banker-base', auto_load_adapters=True, adapter_subdir='author')
        factory('/b', tmp_path)([{'raw': 'p'}])
        load = [r for r in server.requests if r['path'].endswith('load_lora_adapter')][0]
        assert json.loads(load['body'])['lora_path'] == str((tmp_path / 'author').resolve())
