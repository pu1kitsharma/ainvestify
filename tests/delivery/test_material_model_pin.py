import json

import pytest

from delivery import material_stage


def test_material_author_pin_freezes_before_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(material_stage, 'memo_directory', lambda job: tmp_path)
    monkeypatch.setattr(material_stage, '_installed_material_digest',
                        lambda name: 'a' * 64)
    (tmp_path / 'model.json').write_text(json.dumps({
        'profiles': {'draft': 'qwen3.5:9b'}}))

    def private_call(*args, **kwargs):
        (tmp_path / 'material_result.json').write_text(json.dumps({
            'state': 'blocked', 'reason': 'synthetic_stop'}))

    monkeypatch.setattr(material_stage, 'run_private', private_call)
    job = {'input_revision': 'r' * 64}
    memo = {'state': 'accepted', 'source_hash': 's' * 64,
            'sections': [['Overview', 'Source-bound draft']]}
    result = material_stage.run_material_pass(
        job, memo, timeout=90, draft_model='qwen3:14b')
    assert result['state'] == 'blocked'
    request = json.loads((tmp_path / 'material_request.json').read_text())
    assert request['draft_model'] == {
        'name': 'qwen3:14b', 'digest': 'a' * 64,
        'options': material_stage.MATERIAL_AUTHOR_OPTIONS}
    assert material_stage._draft_model_pin(request, json.loads(
        (tmp_path / 'model.json').read_text())) == 'qwen3:14b'
    with pytest.raises(ValueError, match='new immutable branch'):
        material_stage.run_material_pass(
            job, memo, timeout=90, draft_model='qwen3.5:9b')
    assert json.loads((tmp_path / 'material_request.json').read_text()) == request
