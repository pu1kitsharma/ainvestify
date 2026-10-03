"""Synthetic finite local slide remediation after an exact reviewer finding."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_slides import (STRUCTURED_SLIDE_INSTRUCTION,
    StructuredDeckSpec, project_structured, render_sections)
from scripts.private_material_repair_worker import repair_materials


SECTIONS = [['Synthetic product',
    'The synthetic product claim requires primary review [S1]. Financial statements are unavailable [S1].',
    '[S1] Synthetic exact source']]
OPTIONS = {'thinking': False, 'max_tokens': 1500,
           'context_tokens': 16384, 'temperature': 0}


def _slide(heading, text, purpose='other'):
    return {'heading': heading,
            'sentences': [{'text': text, 'source_ids': ['S1']}],
            'layout': 'statement', 'purpose': purpose}


ORIGINAL = StructuredDeckSpec.model_validate({'slides': [
    _slide('Synthetic company overview',
           'The synthetic product claim requires primary review before any investment decision can be made'),
    _slide('Synthetic diligence plan',
           'The synthetic product claim requires primary review before any investment decision can be made'),
]})


class FakeRepairModel:
    name = 'qwen3.5:9b'
    last_response_text = ''
    last_route = {}

    def __init__(self, slide):
        self.slide = slide
        self.calls = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == 'material_review_slide_repair'
        self.calls += 1
        result = schema.model_validate({'slide_index': 0, 'slide': self.slide})
        self.last_response_text = result.model_dump_json()
        self.last_route = {'model': self.name, **OPTIONS}
        return result


def _request(tmp_path):
    rendered = render_sections(project_structured(ORIGINAL, SECTIONS), SECTIONS)
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'material_digest': 'material',
            'blocked_review_digest': 'review',
            'review_finding': {'deck': 'intro_deck', 'slide_index': 0,
                'issue': 'heading_body_mismatch', 'heading_quote': 'Synthetic company overview',
                'body_quote': 'synthetic product claim requires primary review',
                'explanation': 'The source-bound slide should clarify its actual diligence need.'},
            'target_deck': 'intro_deck', 'target_slide_index': 0,
            'target_deck_spec': ORIGINAL.model_dump(mode='json'),
            'original_decks': {'intro_deck': {'response_id': 'original',
                                             'response_ids': ['original'],
                                             'sections': [list(row) for row in rendered]},
                               'pitch_deck': {'response_id': 'other',
                                              'response_ids': ['other'],
                                              'sections': [list(row) for row in rendered]}},
            'memo_sections': SECTIONS,
            'repair_model': {'name': 'qwen3.5:9b', 'digest': 'synthetic-model',
                             'options': OPTIONS}}
    (tmp_path / 'material_repair_request.json').write_text(json.dumps({**base,
        'digest': digest(base)}))
    (tmp_path / 'material_repair_budget.json').write_text(json.dumps({'seconds': 90}))
    return base


def test_one_model_authored_slide_repair_replays_exactly(tmp_path):
    _request(tmp_path)
    replacement = _slide('Synthetic product evidence gap',
        'Financial statements are unavailable and the synthetic product claim requires primary review',
        'other')
    model = FakeRepairModel(replacement)
    accepted = repair_materials(tmp_path, model)
    assert accepted['state'] == 'accepted' and model.calls == 1
    assert accepted['decks']['intro_deck']['sections'][0][0] == 'Synthetic product evidence gap'
    assert repair_materials(tmp_path, FakeRepairModel(replacement)) == accepted
    rows = json.loads((tmp_path / 'material_repair_attempts.json').read_text())
    rows[0]['answer']['slide']['heading'] = 'Forged heading'
    (tmp_path / 'material_repair_attempts.json').write_text(json.dumps(rows))
    with pytest.raises(ValueError, match='differs from its original response'):
        repair_materials(tmp_path, FakeRepairModel(replacement))


def test_unchanged_slide_is_blocked_without_a_retry(tmp_path):
    _request(tmp_path)
    model = FakeRepairModel(ORIGINAL.slides[0].model_dump(mode='json'))
    result = repair_materials(tmp_path, model)
    assert result['state'] == 'blocked' and model.calls == 1
    assert len(json.loads((tmp_path / 'material_repair_attempts.json').read_text())) == 1


def test_versioned_unchanged_slide_is_recorded_as_dispute_not_repair(tmp_path):
    base = _request(tmp_path)
    base['repair_contract'] = 'review_dispute_v1'
    (tmp_path / 'material_repair_request.json').write_text(json.dumps({**base,
        'digest': digest(base)}))
    model = FakeRepairModel(ORIGINAL.slides[0].model_dump(mode='json'))
    result = repair_materials(tmp_path, model)
    assert result['state'] == 'disputed_without_change' and model.calls == 1
    assert repair_materials(tmp_path, FakeRepairModel({})) == result
    assert len(json.loads((tmp_path / 'material_repair_attempts.json').read_text())) == 1


def test_repair_gateway_binds_original_deck_review_and_replay(tmp_path, monkeypatch):
    from delivery import material_repair_stage as stage
    job = {'input_revision': 'synthetic'}
    memo = {'source_hash': 'source', 'sections': SECTIONS}
    base = _request(tmp_path)
    material = {'state': 'accepted', 'source_hash': 'source',
                'memo_digest': 'memo', 'decks': base['original_decks']}
    blocked = {'state': 'blocked', 'review': {'findings': [base['review_finding']]}}
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {
        'draft': 'qwen3.5:9b', 'corrector': 'qwen3.5:9b'}}))
    (tmp_path / 'material_request.json').write_text(json.dumps({
        'sections': SECTIONS, 'replay_contracts': {'intro_deck': 'structured'}}))
    raw = ORIGINAL.model_dump_json()
    row = {'id': 'response_1', 'task': 'material_intro_deck',
           'instruction': STRUCTURED_SLIDE_INSTRUCTION,
           'input': {'kind': 'intro_deck', 'input_revision': 'synthetic',
                     'source_hash': 'source', 'memo_digest': 'memo', 'sections': SECTIONS},
           'schema': StructuredDeckSpec.model_json_schema(),
           'answer': ORIGINAL.model_dump(mode='json'), 'raw_response': raw,
           'response_hash': digest(raw), 'model': 'qwen3.5:9b'}
    (tmp_path / 'material_attempts.json').write_text(json.dumps([row]))
    monkeypatch.setattr(stage, 'memo_directory', lambda unused: tmp_path)
    monkeypatch.setattr(stage, 'validate_material_checkpoint',
                        lambda unused_job, unused_memo, exact: exact)
    monkeypatch.setattr(stage, 'validate_material_review_checkpoint',
                        lambda unused_job, unused_memo, unused_material, review,
                        expected_state: review)
    monkeypatch.setattr(stage, '_installed_digest', lambda name: 'synthetic-model')
    replacement = _slide('Synthetic product evidence gap',
        'Financial statements are unavailable and the synthetic product claim requires primary review')
    model = FakeRepairModel(replacement)

    def fake_private(command, root, **kwargs):
        result = repair_materials(root, model)
        (root / 'material_repair_result.json').write_text(json.dumps(result))

    monkeypatch.setattr(stage, 'run_private', fake_private)
    repaired = stage.run_material_repair_pass(job, memo, material, blocked, timeout=100)
    assert repaired['state'] == 'accepted' and model.calls == 1
    assert stage.validate_material_repair_checkpoint(job, memo, repaired) == repaired
    changed = {**repaired, 'decks': {**repaired['decks'],
        'intro_deck': {'sections': [['Forged', '', '', '']]}}}
    with pytest.raises(ValueError, match='checkpoint differs'):
        stage.validate_material_repair_checkpoint(job, memo, changed)
