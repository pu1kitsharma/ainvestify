"""Private material projection consumes exact recorded source-unit revisions."""
import json
import pytest
from agents.inference.model_authorship import digest
from scripts import evaluate_private_material_acceptance as material
from scripts import private_source_unit_worker as worker
from tests.research.test_private_source_unit_worker import setup, invoke, PIN


def fixture(tmp_path, monkeypatch):
    parent = tmp_path / 'private-case'
    parent.mkdir()
    memo_root, content_root = parent / 'memo', parent / 'units'
    memo_root.mkdir(); content_root.mkdir()
    body, models = setup(content_root)
    history = []
    for number, phase in enumerate(worker.PHASES, 1):
        result = invoke(content_root, phase, models)
        history.append({'pass': number, 'phase': phase, 'state': result['state']})
    worker._write(content_root, 'content_passes.json', history)
    worker._write(content_root, 'content_result.json', result)
    revision = worker.load_source_unit_revision(content_root)
    revised, gate = worker.replay_source_unit_revision(body['memo'], body['sources'], revision)
    request = {'company': 'Synthetic company', 'sources': body['sources'], 'input_revision': 'f' * 64}
    profile = {'memo_draft_contract': 'memo-cards-v13', 'profiles': {
        'draft': PIN['name'], 'review': PIN['name']},
        'memo_role_model_digests': {'draft': PIN['digest'], 'review': PIN['digest']}}
    for name, value in [('request', request), ('model', profile), ('attempts', []),
                        ('result', {'state': 'accepted', 'acceptance_scope': 'local_model_checks_only',
                                    'independent_review': 'pending', 'accepted': {'memo': body['memo']}})]:
        (memo_root / f'{name}.json').write_text(json.dumps(value))
    (parent / 'ingest_result.json').write_text(json.dumps({'state': 'parsed', 'memo_source_sha256': 'f' * 64}))
    monkeypatch.setattr(material, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(material, '_installed_digest', lambda name: PIN['digest'])
    def renderer(original, sources, attempts, projection=None, content_revision=None):
        assert original['memo'] == body['memo']
        updated, replayed = worker.replay_source_unit_revision(original['memo'], sources, content_revision)
        assert replayed == gate
        return [('Recommendation', updated['recommendation_reason'], [])]
    monkeypatch.setattr(material, 'renderable_sections', renderer)
    def candidates(accepted):
        assert accepted['memo'] == revised
        return {}
    monkeypatch.setattr(material, 'financial_unknown_candidates', candidates)
    monkeypatch.setattr(material, 'memo_sentence_candidates', candidates)
    return memo_root, content_root, revised, gate


def test_private_material_projection_uses_revised_recorded_units(tmp_path, monkeypatch):
    memo_root, content_root, revised, gate = fixture(tmp_path, monkeypatch)
    result = material._memo_projection(memo_root, content_root=content_root)
    assert result['sections'][0][1] == revised['recommendation_reason']
    assert result['content_revision'] == {'root': str(content_root), 'record': gate}
    assert result['memo_digest'] == digest({'memo': revised})
    assert result['content_revision']['record']['investment_approval'] is False


@pytest.mark.parametrize('changed', ['history', 'gate', 'final_digest'])
def test_private_material_projection_rejects_incomplete_or_changed_acceptance(tmp_path, monkeypatch, changed):
    memo_root, content_root, _, _ = fixture(tmp_path, monkeypatch)
    if changed == 'history':
        file = content_root / 'content_passes.json'
        rows = json.loads(file.read_text()); rows[0]['state'] = 'started'
        file.write_text(json.dumps(rows))
    else:
        file = content_root / 'content_result.json'
        result = json.loads(file.read_text())
        if changed == 'gate': result['content_review']['investment_approval'] = True
        else: result['final_memo_digest'] = 'e' * 64
        file.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='completed ordered phases|exact replay'):
        material._memo_projection(memo_root, content_root=content_root)


@pytest.mark.parametrize("flow_version, section_contract", [(2, None), (3, None),
    (3, "memo-section-units-author-v2"), (3, "memo-section-units-author-v3"), (4, "memo-section-units-author-v3"), (4, "memo-section-units-author-v4"), (4, "memo-section-units-author-v5"), (4, "memo-section-units-author-v6"), (4, "memo-section-units-author-v7"), (4, "memo-section-units-author-v8")])
def test_full_memo_flow_projection_requires_all_five_phase_records(tmp_path, monkeypatch, flow_version, section_contract):
    from delivery.source_unit_content_stage import FLOW_V2, FLOW_V3, FLOW_V4, flow_config
    flow = FLOW_V4 if flow_version == 4 else FLOW_V3 if flow_version == 3 else FLOW_V2
    phases, _ = flow_config(flow)
    memo_root, content_root, revised, old_gate = fixture(tmp_path, monkeypatch)
    file = content_root / 'content_request.json'
    request = json.loads(file.read_text())
    request['flow_contract'] = flow
    request['author_contract'] = 'memo-source-unit-author-v7'
    if section_contract is not None:
        request['section_author_contract'] = section_contract
    if flow_version == 4:
        request['core_author_pin'] = PIN.copy()
    if section_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8'}:
        request['core_reviewer_pin'] = PIN.copy()
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    file.write_text(json.dumps(request))
    gate = {**old_gate, 'contract': flow,
            **({'core_reviewer_pin': request['core_reviewer_pin']} if section_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8'} else {}),
            **({'core_author_pin': request['core_author_pin']} if flow_version == 4 else {}),
            **({'section_author_contract': section_contract} if section_contract is not None else {}),
            'coverage': ['recommendation_reason', 'unknowns', 'investment_thesis',
                         'business_and_market', 'differentiation_and_execution',
                         'risks_and_countercase', 'diligence_plan']}
    result_file = content_root / 'content_result.json'
    result = json.loads(result_file.read_text()); result['content_review'] = gate
    result_file.write_text(json.dumps(result))
    monkeypatch.setattr(worker, 'load_source_unit_revision', lambda root: {'contract': flow})
    monkeypatch.setattr(worker, 'replay_source_unit_revision', lambda memo, sources, record: (revised, gate))
    monkeypatch.setattr(material, 'renderable_sections', lambda *args, **kwargs:
                        [('Updated memo', revised['recommendation_reason'], [])])
    history_file = content_root / 'content_passes.json'
    # The former three completed phases cannot qualify full memo material projection.
    with pytest.raises(ValueError, match='completed ordered phases|pass history changed'):
        material._memo_projection(memo_root, content_root=content_root)
    history_file.write_text(json.dumps([{'pass': number, 'phase': phase,
        'state': 'accepted' if number == len(phases) else 'needs_resume'}
        for number, phase in enumerate(phases, 1)]))
    projection = material._memo_projection(memo_root, content_root=content_root)
    assert projection['content_revision']['record'] == gate
    assert projection['memo_digest'] == digest({'memo': revised})


@pytest.mark.parametrize('legacy_pins', [None, {'draft': 'a' * 64, 'review': 'c' * 64}])
def test_diagnostic_separate_core_writer_preserves_historical_profile_and_rejects_tamper(tmp_path, monkeypatch, legacy_pins):
    from delivery.source_unit_content_stage import FLOW_V4, PHASES_V4
    memo_root, content_root, revised, old_gate = fixture(tmp_path, monkeypatch)
    model_file = memo_root / 'model.json'
    historical = {'memo_draft_contract': 'memo-cards-v13',
        'profiles': {'draft': 'qwen3.5:9b', 'review': 'qwen3:14b'},
        'memo_role_model_digests': legacy_pins, 'memo_causal_review_model_digest': 'c' * 64}
    model_file.write_text(json.dumps(historical))
    original_profile_bytes = model_file.read_bytes()
    installed = {'qwen3.5:9b': 'a' * 64, 'qwen3:14b': 'c' * 64}
    monkeypatch.setattr(material, '_installed_digest', lambda name: installed[name])
    core_pin = {'name': 'qwen3:14b', 'digest': 'c' * 64}
    request_file = content_root / 'content_request.json'
    request = json.loads(request_file.read_text())
    request.update(flow_contract=FLOW_V4, author_contract='memo-source-unit-author-v7',
                   section_author_contract='memo-section-units-author-v6', core_author_pin=core_pin)
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    request_file.write_text(json.dumps(request))
    gate = {**old_gate, 'contract': FLOW_V4, 'core_author_pin': core_pin,
            'section_author_contract': request['section_author_contract']}
    result_file = content_root / 'content_result.json'
    result = json.loads(result_file.read_text()); result['content_review'] = gate
    result_file.write_text(json.dumps(result))
    worker._write(content_root, 'content_passes.json', [
        {'pass': number, 'phase': phase, 'state': 'accepted' if number == 15 else 'needs_resume'}
        for number, phase in enumerate(PHASES_V4, 1)])
    monkeypatch.setattr(worker, 'load_source_unit_revision', lambda root: {'contract': FLOW_V4, 'core_author_pin': core_pin})
    monkeypatch.setattr(worker, 'replay_source_unit_revision', lambda memo, sources, record: (revised, gate))
    monkeypatch.setattr(material, 'renderable_sections', lambda *args, **kwargs:
                        [('Updated memo', revised['recommendation_reason'], [])])
    projection = material._memo_projection(memo_root, content_root=content_root)
    assert projection['content_revision']['record']['core_author_pin'] == core_pin
    assert model_file.read_bytes() == original_profile_bytes
    # Even another installed model cannot replace the writer bound by raw replay.
    request['core_author_pin'] = {'name': 'qwen3.5:9b', 'digest': 'a' * 64}
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    request_file.write_text(json.dumps(request))
    with pytest.raises(ValueError, match='core author role differs from exact replay'):
        material._memo_projection(memo_root, content_root=content_root)
    request['core_author_pin'] = {'name': 'qwen3:14b', 'digest': 'd' * 64}
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    request_file.write_text(json.dumps(request))
    with pytest.raises(ValueError, match='Installed source-unit core author digest changed'):
        material._memo_projection(memo_root, content_root=content_root)
