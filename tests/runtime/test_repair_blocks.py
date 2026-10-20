"""Offline tests (fake transports only): repair protocol, fault classes, block ledger, budgets."""
import json
import pytest
from agents.runtime import AgentRuntime, Budget
from agents.runtime.loop import InfraFault, RepairPolicy
from agents.runtime.banker_session import NativeOllamaTransport, run_banker_session

EP = 'http://127.0.0.1:11434/v1'
SCHEMA = {'type': 'object', 'properties': {'values': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'number'}}}},
          'required': ['values'], 'additionalProperties': False}


def reply(calls=None, content='done'):
    return {'model': 'installed-test', 'usage': {'total_tokens': 10},
            'choices': [{'finish_reason': 'tool_calls' if calls else 'stop',
                         'message': {'role': 'assistant', 'content': content, 'tool_calls': calls or []}}]}


def call(identifier, arguments, name='wb.write_block'):
    return {'type': 'function', 'id': identifier, 'function': {'name': name, 'arguments': arguments if isinstance(arguments, str) else json.dumps(arguments)}}


def make_tool(effects, name='wb.write_block', ok=True):
    def validate(arguments):
        if not isinstance(arguments.get('values'), list):
            raise ValueError('$.values: invalid JSON type')
    def run(**arguments):
        effects.append(arguments)
        return {'version': 'tools/v1', 'ok': ok, 'tool': name, 'result': {}, 'errors': [] if ok else [{'code': 'ToolExecutionError', 'message': 'no sheet'}]}
    return {name: {'validate': validate, 'call': run, 'schema': {'description': 'write', 'parameters': SCHEMA}}}


def rt(tmp_path, transport, tools, repair=RepairPolicy(), **kw):
    return AgentRuntime(endpoint=EP, model='installed-test', transport=transport, tools=tools, directory=tmp_path,
                        repair=repair, **kw)


def scripted(responses, seen=None):
    queue = iter(responses)
    def transport(**kw):
        if seen is not None: seen.append(json.loads(json.dumps(kw['request'])))
        return next(queue)
    return transport


def test_error_then_repair_then_success_with_instructive_observation(tmp_path):
    effects, seen = [], []
    bad = call('c1', {'values': '[[1,2]]'})            # the D1 failure: stringified array
    good = call('c2', {'values': [[1, 2]]})
    state = rt(tmp_path, scripted([reply([bad]), reply([good]), reply(content='{"status":"block_done"}')], seen),
               make_tool(effects)).run('modeling_analyst', 'mandate')
    assert state['status'] == 'human_review_required' and state['calls'] == 3
    assert len(effects) == 1 and effects[0] == {'values': [[1, 2]]}   # failed call had no effect
    assert state['repair_calls'] == 1 and state['bad_turns_consecutive'] == 0 and state['bad_turns_total'] == 1
    tool_msg = json.loads(seen[1]['messages'][-1]['content'])
    assert tool_msg['version'] == 'tools/v1' and tool_msg['ok'] is False
    err = tool_msg['errors'][0]
    assert err['code'] == 'ArgumentValidationError' and err['path'] == '$.values'
    assert '"type": "array"' in err['expected_schema'] and 'arithmetic' in err['hint']
    # each repair is a NEW model request, never identical bytes
    assert len({json.dumps(r, sort_keys=True) for r in seen}) == 3
    assert len(state['request_hashes']) == len(set(state['request_hashes'])) == 3
    kinds = [json.loads(x)['kind'] for x in (tmp_path / 'trajectory.jsonl').read_text().splitlines()]
    assert 'tool_failure' in kinds
    failure = [json.loads(x) for x in (tmp_path / 'trajectory.jsonl').read_text().splitlines() if json.loads(x)['kind'] == 'tool_failure'][0]
    assert failure['raw_arguments'] == bad['function']['arguments'] and failure['pre_effect'] is True


def test_parse_error_is_model_visible(tmp_path):
    seen, effects = [], []
    state = rt(tmp_path, scripted([reply([call('c1', '{"values": [[1/12]]}')]), reply(content='x')], seen), make_tool(effects)).run('modeling_analyst', 'm')
    assert state['status'] == 'human_review_required' and not effects
    assert json.loads(seen[1]['messages'][-1]['content'])['errors'][0]['code'] == 'ArgumentParseError'


def test_repair_cap_consecutive(tmp_path):
    effects = []
    responses = [reply([call(f'c{i}', {'values': f'bad{i}'})]) for i in range(1, 8)]
    state = rt(tmp_path, scripted(responses), make_tool(effects), repair=RepairPolicy(2, 6)).run('modeling_analyst', 'm')
    assert state['status'] == 'repair_cap_reached' and state['fault_class'] == 'model_error'
    assert state['calls'] == 3 and not effects          # 1 original + 2 repairs, then stop


def test_repair_cap_total_across_recoveries(tmp_path):
    big = Budget(seconds=120, calls=12, profile='diagnostic')
    effects = []
    seq = []
    for i in range(1, 4):
        seq += [reply([call(f'b{i}', {'values': f'bad{i}'})]), reply([call(f'g{i}', {'values': [[i]]})])]
    seq += [reply([call('b9', {'values': 'bad9'})])]
    state = rt(tmp_path, scripted(seq), make_tool(effects), repair=RepairPolicy(2, 3), budget=big).run('modeling_analyst', 'm')
    assert state['status'] == 'repair_cap_reached' and state['bad_turns_total'] == 4 and len(effects) == 3


def test_identical_failed_call_is_refused_not_executed(tmp_path):
    effects, seen = [], []
    same = {'values': 'x'}
    state = rt(tmp_path, scripted([reply([call('c1', same)]), reply([call('c2', same)]), reply([call('c3', {'values': [[1]]})]), reply()], seen),
               make_tool(effects)).run('modeling_analyst', 'm')
    assert json.loads(seen[2]['messages'][-1]['content'])['errors'][0]['code'] == 'IdenticalFailedCall'
    assert len(effects) == 1 and state['status'] == 'human_review_required'


def test_identical_model_request_replay_is_refused(tmp_path):
    runtime = rt(tmp_path, lambda **kw: reply(), {})
    runtime.state['messages'] = []
    runtime.run('im_writer', 'm')
    # forged duplicate: a model request whose hash already exists must fail closed
    runtime.state['status'] = 'paused'
    runtime.state['messages'] = runtime.state['messages'][:2]
    runtime.state['calls'] = 0
    runtime.state['tokens'] = 0
    state = runtime.run('im_writer', None, resume=True)
    assert state['status'] == 'failed' and 'identical model request' in state['error']


def test_without_repair_policy_first_error_still_ends_pass(tmp_path):
    state = rt(tmp_path, scripted([reply([call('c1', {'values': 'x'})])]), make_tool([]), repair=None).run('modeling_analyst', 'm')
    assert state['status'] == 'failed' and state['calls'] == 1


def test_batch_stops_at_first_failure_and_skips_rest(tmp_path):
    effects, seen = [], []
    batch = [call('a', {'values': 'bad'}), call('b', {'values': [[1]]})]
    state = rt(tmp_path, scripted([reply(batch), reply()], seen), make_tool(effects)).run('modeling_analyst', 'm')
    assert not effects
    tail = [json.loads(m['content']) for m in seen[1]['messages'] if m.get('role') == 'tool']
    assert [t['errors'][0]['code'] for t in tail] == ['ArgumentValidationError', 'SkippedAfterFailure']
    assert state['tool_call_ids'] == ['a', 'b']


def test_tool_returned_error_counts_toward_cap(tmp_path):
    effects = []
    responses = [reply([call(f'c{i}', {'values': [[i]]})]) for i in range(1, 6)]
    state = rt(tmp_path, scripted(responses), make_tool(effects, ok=False), repair=RepairPolicy(2, 6)).run('modeling_analyst', 'm')
    assert state['status'] == 'repair_cap_reached' and len(effects) == 3   # executed errors are re-observed by the model


def test_not_allowed_tool_is_repairable_when_enabled(tmp_path):
    state = rt(tmp_path, scripted([reply([call('c1', {}, name='web.search')]), reply()]), make_tool([])).run('modeling_analyst', 'm')
    assert state['status'] == 'human_review_required' and state['tool_failures'][0]['code'] == 'ToolNotAllowed'


# ---- fault classification ------------------------------------------------------------
def test_infra_fault_classified_and_not_model_error(tmp_path):
    def fail(**kw): raise InfraFault('empty native response frame')
    state = rt(tmp_path, fail, {}).run('im_writer', 'm')
    assert state['status'] == 'failed' and state['fault_class'] == 'infra_fault' and state['faults'][0]['fault_class'] == 'infra_fault'


def test_connection_error_is_infra_fault(tmp_path):
    def fail(**kw): raise ConnectionRefusedError('refused')
    assert rt(tmp_path, fail, {}).run('im_writer', 'm')['fault_class'] == 'infra_fault'


def test_malformed_response_is_model_error(tmp_path):
    response = reply(); response['choices'][0]['finish_reason'] = 'length'
    state = rt(tmp_path, lambda **kw: response, {}).run('im_writer', 'm')
    assert state['fault_class'] == 'model_error'


def test_timeout_at_deadline_is_budget_exhausted_not_infra(tmp_path):
    now = [0.0]
    def fail(**kw):
        now[0] = 120.0
        raise TimeoutError('native response deadline')
    state = rt(tmp_path, fail, {}, clock=lambda: now[0]).run('im_writer', 'm')
    assert state['status'] == 'budget_exhausted' and state['fault_class'] == 'budget_exhausted'


def test_budget_calls_exhausted_labelled(tmp_path):
    effects = []
    responses = [reply([call(f'c{i}', {'values': [[i]]})]) for i in range(1, 4)]
    state = rt(tmp_path, scripted(responses), make_tool(effects), budget=Budget(calls=2)).run('modeling_analyst', 'm')
    assert state['status'] == 'budget_exhausted' and state['fault_class'] == 'budget_exhausted' and state['calls'] == 2


def test_single_labelled_infra_resume(tmp_path):
    seen, attempts = [], []
    def transport(**kw):
        seen.append(kw['request'])
        attempts.append(1)
        if len(attempts) == 1: raise InfraFault('empty frame')
        return reply()
    runtime = rt(tmp_path, transport, {})
    assert runtime.run('im_writer', 'm')['fault_class'] == 'infra_fault'
    state = runtime.resume_after_infra_fault('im_writer')
    assert state['status'] == 'human_review_required' and state['infra_resumes'] == 1 and state['calls'] == 2
    assert seen[0]['messages'] == seen[1]['messages']      # same session state, not a content change
    kinds = [json.loads(x) for x in (tmp_path / 'trajectory.jsonl').read_text().splitlines()]
    assert any(k['kind'] == 'infra_resume' and 'not a content retry' in k['label'] for k in kinds)
    with pytest.raises(ValueError): runtime.resume_after_infra_fault('im_writer')


def test_second_infra_fault_is_not_resumed(tmp_path):
    def fail(**kw): raise InfraFault('empty frame')
    runtime = rt(tmp_path, fail, {})
    runtime.run('im_writer', 'm')
    assert runtime.resume_after_infra_fault('im_writer')['fault_class'] == 'infra_fault'
    with pytest.raises(ValueError): runtime.resume_after_infra_fault('im_writer')


def test_resume_refused_for_model_error(tmp_path):
    response = reply(); response['choices'][0]['finish_reason'] = 'length'
    runtime = rt(tmp_path, lambda **kw: response, {})
    runtime.run('im_writer', 'm')
    with pytest.raises(ValueError): runtime.resume_after_infra_fault('im_writer')


class _Resp:
    status = 200
    def __init__(self, data): self.data = data
    def getheader(self, name): return str(len(self.data))
    def read(self, n):
        out, self.data = self.data[:n], self.data[n:]
        return out


class _Conn:
    sock = None
    def __init__(self, data, status=200): self.response = _Resp(data); self.response.status = status
    def request(self, *a, **k): pass
    def getresponse(self): return self.response
    def close(self): pass


def test_native_empty_frame_is_infra_fault_with_receipt():
    raw = json.dumps({'model': '', 'created_at': 'x', 'message': {'role': 'assistant', 'content': ''}, 'done': False}).encode()
    receipts = []
    transport = NativeOllamaTransport(connection_factory=lambda *a, **k: _Conn(raw))
    with pytest.raises(InfraFault):
        transport(endpoint=EP, request={'model': 'installed-test', 'messages': [], 'max_tokens': 2200}, timeout=5,
                  receipt=lambda *a: receipts.append(a))
    assert receipts[1][1] == raw           # raw response is retained even for the fault


def test_native_http_5xx_is_infra_fault_and_other_mismatch_is_not():
    t5 = NativeOllamaTransport(connection_factory=lambda *a, **k: _Conn(b'{}', 503))
    with pytest.raises(InfraFault):
        t5(endpoint=EP, request={'model': 'installed-test', 'messages': [], 'max_tokens': 2200}, timeout=5)
    raw = json.dumps({'model': 'other', 'done': True, 'done_reason': 'stop', 'prompt_eval_count': 1, 'eval_count': 1,
                      'message': {'role': 'assistant', 'content': 'x'}}).encode()
    tm = NativeOllamaTransport(connection_factory=lambda *a, **k: _Conn(raw))
    with pytest.raises(ValueError) as caught:
        tm(endpoint=EP, request={'model': 'installed-test', 'messages': [], 'max_tokens': 2200}, timeout=5)
    assert not isinstance(caught.value, InfraFault)


def test_native_transport_limits_are_explicit():
    with pytest.raises(ValueError): NativeOllamaTransport(max_timeout=0)
    with pytest.raises(ValueError):
        NativeOllamaTransport()(endpoint=EP, request={'model': 'm', 'messages': [], 'max_tokens': 2200}, timeout=300)
    NativeOllamaTransport(max_timeout=600)   # explicit diagnostic transport


def test_receipts_for_every_call_including_repairs(tmp_path):
    seen = []
    queue = iter([reply([call('c1', {'values': 'bad'})]), reply([call('c2', {'values': [[1]]})]), reply()])
    class Transport:
        supports_receipts = True
        def __call__(self, *, endpoint, request, timeout, receipt):
            body = json.dumps(request).encode()
            receipt('request', body, {'complete': True})
            out = next(queue)
            receipt('response', json.dumps(out).encode(), {'complete': True})
            return out
    state = rt(tmp_path, Transport(), make_tool([])).run('modeling_analyst', 'm')
    assert state['calls'] == 3 and len(state['receipts']) == 6
    assert sorted({r['call'] for r in state['receipts']}) == [1, 2, 3]
    AgentRuntime.open(directory=tmp_path, endpoint=EP, model='installed-test', transport=Transport(), tools=make_tool([]), repair=RepairPolicy())


# ---- budgets ------------------------------------------------------------------------
def test_default_budget_limits_preserved_and_diagnostic_is_explicit():
    assert Budget().seconds == 120 and Budget().calls == 6 and Budget().profile == 'default'
    with pytest.raises(ValueError): Budget(seconds=300)
    with pytest.raises(ValueError): Budget(calls=12)
    d = Budget(seconds=300, calls=12, profile='diagnostic', call_seconds=240)
    assert d.profile == 'diagnostic'
    with pytest.raises(ValueError): Budget(seconds=1200, profile='diagnostic')
    with pytest.raises(ValueError): Budget(profile='unlabelled')
    with pytest.raises(ValueError): Budget(seconds=60, call_seconds=90)
    with pytest.raises(ValueError): RepairPolicy(0, 1)
    with pytest.raises(ValueError): RepairPolicy(5, 6)


def test_diagnostic_profile_allows_more_calls_than_role_steps(tmp_path):
    effects = []
    responses = [reply([call(f'c{i}', {'values': [[i]]})]) for i in range(1, 12)]
    state = rt(tmp_path, scripted(responses), make_tool(effects), budget=Budget(seconds=120, calls=8, profile='diagnostic')).run('modeling_analyst', 'm')
    assert state['calls'] == 8 and state['status'] == 'budget_exhausted'


# ---- block ledger ----------------------------------------------------------------------
def spec(**kw):
    return json.dumps({'status': 'block_done', 'unresolved_findings': [], **kw})


def block_factory(plans):
    """plans: list (one per block) of lists of responses; transport per block."""
    index = []
    def factory():
        index.append(1)
        responses = iter(plans[len(index) - 1] if len(index) <= len(plans) else [reply()])
        def transport(**kw): return next(responses)
        return transport
    return factory


def test_block_ledger_progresses_with_repair_and_merges_specs(tmp_path):
    p1 = [reply([call('a1', {'title': 'History'}, 'wb.add_sheet'),
                 call('a2', {'sheet': 'History', 'start': 'A1', 'values': '[["Rev",1]]'}, 'wb.write_block')]),
          reply([call('b1', {'sheet': 'History', 'start': 'A1', 'values': [['Rev', 100], ['Cost', 40], ['Profit', '=B1-B2']]}, 'wb.write_block')]),
          reply(content=spec(metrics={'profit': {'sheet': 'History', 'cell': 'B3', 'unit': 'k'}}))]
    p2 = [reply([call('d1', {'title': 'Drivers'}, 'wb.add_sheet'),
                 call('d2', {'sheet': 'Drivers', 'start': 'A1', 'values': [['Growth', 0.1]]}, 'wb.write_block')]),
          reply(content=spec(assumptions=[{'sheet': 'Drivers', 'cell': 'B1'}]))]
    report = run_banker_session(case={'sources': [{'text': 'synthetic'}]}, output=tmp_path / 'run', model='installed-test',
                                mode='blocks', repair=RepairPolicy(), block_ids=['hist_is', 'drivers'],
                                transport_factory=block_factory([p1, p2, [reply(content='{}')]]))
    assert [b['id'] for b in report['blocks']] == ['hist_is', 'drivers']
    assert all(b['completed'] for b in report['blocks']) and report['blocks_completed'] == 2
    first = report['blocks'][0]
    assert first['calls'] == 3 and first['repair']['repair_calls'] == 1 and first['cells_after'] > first['cells_before'] == 0
    assert report['model_output_spec']['metrics']['profit']['cell'] == 'B3'
    assert report['model_output_spec']['assumptions'] == [{'sheet': 'Drivers', 'cell': 'B1'}]
    assert (tmp_path / 'run/block-01-hist_is/checkpoint.json').is_file() and (tmp_path / 'run/block-02-drivers-diagnostic.json').is_file()
    assert report['repair_totals']['repair_calls'] >= 1 and report['fault_summary']['model_error'] == 0
    assert report['budget_profile'] == 'default' and report['bounds_per_pass']['seconds'] == 120
    # block 2 saw block 1's cells in its mandate (state carried through the digest)
    prompt2 = json.loads((tmp_path / 'run/block-02-drivers/trajectory.jsonl').read_text().splitlines()[0])['request']['messages'][1]['content']
    assert 'CURRENT BLOCK [drivers]' in prompt2 and 'Profit' in prompt2 and 'PREVIOUS BLOCK DIAGNOSTIC' in prompt2


def test_block_failure_is_labelled_and_does_not_hide_infra_vs_model(tmp_path):
    def factory_builder():
        n = []
        def factory():
            n.append(1)
            k = len(n)
            def transport(**kw):
                if k == 1: raise InfraFault('empty native response frame')
                if k == 2: return reply([call('x', {'sheet': 'S', 'start': 'A1', 'values': 'bad'}, 'wb.write_block')])
                return reply()
            return transport
        return factory
    report = run_banker_session(case={'sources': [{'text': 's'}]}, output=tmp_path / 'run', model='installed-test', mode='blocks',
                                repair=RepairPolicy(1, 1), block_ids=['hist_is', 'drivers'], transport_factory=factory_builder())
    assert report['status'] == 'modeling_failed'
    assert report['blocks'][0]['fault_class'] == 'infra_fault'
    assert report['blocks'][1]['fault_class'] == 'model_error'
    assert report['fault_summary']['infra_fault'] == 1 and report['fault_summary']['model_error'] == 1
    assert report['infra_resumes_used'] == 0


def test_block_session_infra_resume_once_only(tmp_path):
    def factory_builder():
        n = []
        def factory():
            n.append(1)
            def transport(**kw): raise InfraFault('empty native response frame')
            return transport
        return factory, n
    factory, n = factory_builder()
    report = run_banker_session(case={'sources': [{'text': 's'}]}, output=tmp_path / 'run', model='installed-test', mode='blocks',
                                repair=RepairPolicy(), block_ids=['hist_is', 'drivers'], infra_resume=True, transport_factory=factory)
    assert report['infra_resumes_used'] == 1
    assert report['blocks'][0]['calls'] == 2 and report['blocks'][1]['calls'] == 1   # only the first fault was resumed
    assert report['fault_summary']['infra_fault'] == 2 + 0 or report['fault_summary']['infra_fault'] >= 2


def test_stop_on_block_failure_and_session_seconds(tmp_path):
    def factory():
        def transport(**kw): raise ConnectionError('down')
        return transport
    report = run_banker_session(case={'sources': [{'text': 's'}]}, output=tmp_path / 'a', model='installed-test', mode='blocks',
                                block_ids=['hist_is', 'drivers'], stop_on_block_failure=True, transport_factory=factory)
    assert len(report['blocks']) == 1
    report = run_banker_session(case={'sources': [{'text': 's'}]}, output=tmp_path / 'b', model='installed-test', mode='blocks',
                                block_ids=['hist_is', 'drivers'], session_seconds=0, transport_factory=factory)
    assert [b['status'] for b in report['blocks']] == ['not_run', 'not_run'] and report['blocks'][0]['fault_class'] == 'budget_exhausted'


def test_unknown_block_and_scope_selection(tmp_path):
    from agents.runtime.block_ledger import planned_blocks
    assert [b['id'] for b in planned_blocks('pnl')] == ['hist_is']
    assert 'drivers' not in [b['id'] for b in planned_blocks('historical')]
    with pytest.raises(ValueError): planned_blocks('full', ['nope'])


def test_block_answer_key_never_in_prompt(tmp_path):
    with pytest.raises(ValueError):
        run_banker_session(case={'answer_key': {}}, output=tmp_path / 'z', model='installed-test', mode='blocks')


def test_native_output_cap_truncation_is_model_error_not_harness(tmp_path):
    raw = json.dumps({'model': 'installed-test', 'done': True, 'done_reason': 'length', 'prompt_eval_count': 5, 'eval_count': 2200,
                      'message': {'role': 'assistant', 'content': ''}}).encode()
    transport = NativeOllamaTransport(connection_factory=lambda *a, **k: _Conn(raw))
    state = rt(tmp_path, transport, {}).run('im_writer', 'm')
    assert state['status'] == 'failed' and state['fault_class'] == 'model_error'
    assert 'output-token cap' in state['faults'][0]['detail']


def test_failed_mutation_does_not_poison_workbook_for_later_blocks(tmp_path):
    """Regression for the D1/B2 finding: tools rollback (deepcopy) broke the workbook after a comment + failed write."""
    p1 = [reply([call('a1', {'title': 'S'}, 'wb.add_sheet'),
                 call('a2', {'sheet': 'S', 'start': 'A1', 'values': [['x', 1]], 'comment': 'src'}, 'wb.write_block'),
                 call('a3', {'sheet': 'S', 'start': 'A3', 'values': [['x', 1], ['y']]}, 'wb.write_block')]),   # ragged -> tool error
          reply([call('a4', {'sheet': 'S', 'start': 'A3', 'values': [['y', 2], ['z', 3]]}, 'wb.write_block')]),
          reply(content=spec())]
    report = run_banker_session(case={'sources': [{'text': 's'}]}, output=tmp_path / 'run', model='installed-test', mode='blocks',
                                repair=RepairPolicy(), block_ids=['hist_is'], transport_factory=block_factory([p1, [reply(content='{}')]]))
    first = report['blocks'][0]
    assert first['completed'] and first['repair']['bad_turns_total'] == 1
    assert report['workbook_reloads'] >= 1
    from openpyxl import load_workbook
    sheet = load_workbook(tmp_path / 'run/model.xlsx')['S']
    assert sheet['A4'].value == 'z' and sheet['B1'].value == 1 and sheet['A1'].comment is not None


def test_tool_rows_must_be_rectangular_is_in_prompt_examples():
    from agents.runtime.block_ledger import TOOL_EXAMPLES
    assert 'SAME number of cells' in TOOL_EXAMPLES and 'differs from the rejected one' in TOOL_EXAMPLES


def test_per_call_cap_timeout_is_budget_not_infra(tmp_path):
    now = [0.0]
    def slow(**kw):
        now[0] += 200.0                      # the call ran to its explicit per-call cap
        raise TimeoutError('timed out')
    state = rt(tmp_path, slow, {}, clock=lambda: now[0],
               budget=Budget(seconds=600, calls=6, profile='diagnostic', call_seconds=200)).run('im_writer', 'm')
    assert state['fault_class'] == 'budget_exhausted' and state['status'] == 'budget_exhausted'
    def instant(**kw): raise TimeoutError('timed out')
    quick = rt(tmp_path / 'q', instant, {}, budget=Budget(seconds=600, calls=6, profile='diagnostic', call_seconds=200)).run('im_writer', 'm')
    assert quick['fault_class'] == 'infra_fault'
