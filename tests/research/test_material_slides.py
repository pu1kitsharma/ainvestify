"""Synthetic local-model material drafting and raw-response replay."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_slides import (DeckSpec, StructuredDeckSpec,
    STRUCTURED_SLIDE_INSTRUCTION, project_structured, replay_material_rows,
    validate_deck, render_sections)
from scripts.private_material_worker import draft_materials


SECTIONS = [
    ['Synthetic finding', 'Synthetic recorded memo analysis cites [S1].',
     '[S1] https://synthetic.example/source | synthetic version 2024'],
    ['Synthetic risk', 'Synthetic recorded countercase cites [S1].',
     '[S1] https://synthetic.example/source | synthetic version 2024'],
]


def _slide(index, layout='evidence'):
    word = ('Alpha','Beta','Gamma','Delta','Epsilon')[index]
    body = (f'Synthetic model-authored draft point {word} is explicitly illustrative and cites [S1].')
    if index == 4:
        body = 'Synthetic financial results are unverified; the local model requires further diligence [S1].'
    return {'heading': f'Synthetic investor point {word}',
            'body': body,
            'source_sections': [index % len(SECTIONS)], 'layout': layout}


def _structured_slide(index, layout='evidence'):
    word = ('Alpha','Beta','Gamma','Delta','Epsilon')[index]
    purpose = 'financial_unknown' if index == 4 else 'other'
    sentence = ('Synthetic financial results are unverified and require diligent review of the missing statements before any decision'
                if index == 4 else
                f'Synthetic model-authored draft point {word} is explicitly illustrative and requires source review before any decision')
    return {'heading': f'Synthetic investor point {word}',
            'sentences': [{'text': sentence, 'source_ids': ['S1']}],
            'layout': layout,
            'purpose': purpose}


class FakeLocalModel:
    name = 'qwen3.5:9b'
    last_response_text = ''
    last_route = {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task in {'material_intro_deck', 'material_pitch_deck'}
        assert 'sections' in json.loads(evidence)
        count = 2 if task.endswith('intro_deck') else 5
        structured = issubclass(schema, StructuredDeckSpec)
        result = schema.model_validate({'slides': [(_structured_slide if structured else _slide)(
            index, 'comparison' if index % 2 else 'evidence') for index in range(count)]})
        self.last_response_text = result.model_dump_json()
        self.last_route = {'task': task, 'model': self.name}
        return result


class CorrectingLocalModel(FakeLocalModel):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        if task == 'material_intro_deck_patch':
            from agents.research.material_slides import RoutedStructuredSlidePatch
            payload = json.loads(evidence)
            assert payload['slide_index'] == 0
            assert payload['validation_issue']
            result = schema.model_validate(
                {'slide': _structured_slide(0)} if schema is RoutedStructuredSlidePatch
                else {'slide_index': 0, 'slide': _slide(0)})
            self.last_response_text = result.model_dump_json()
            self.last_route = {'task': task, 'model': self.name}
            return result
        result = super().generate_for_task(task, instruction, evidence, schema,
                                           attempt=attempt)
        payload = json.loads(evidence)
        if task == 'material_intro_deck' and 'validation_issue' not in payload:
            changed = result.model_dump()
            if issubclass(schema, StructuredDeckSpec):
                changed['slides'][0]['sentences'][0]['text'] = (
                    'Synthetic 2025 revenue of ₹20 million was reported and requires diligent review')
            else:
                changed['slides'][0]['body'] = ('Synthetic 2025 revenue of ₹20 million was reported [S1]; '
                                               'the model says diligence remains necessary.')
            result = schema.model_validate(changed)
            self.last_response_text = result.model_dump_json()
        return result


class RepeatingBrokenSlideModel(CorrectingLocalModel):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        if task == 'material_intro_deck_patch':
            payload = json.loads(evidence)
            result = schema.model_validate({'slide_index': payload['slide_index'],
                'slide': payload['current_deck']['slides'][payload['slide_index']]})
            self.last_response_text = result.model_dump_json()
            self.last_route = {'task': task, 'model': self.name}
            return result
        return super().generate_for_task(task, instruction, evidence, schema, attempt=attempt)


class FinancialDisclosurePatchModel(FakeLocalModel):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        if task == 'material_pitch_deck_patch':
            payload = json.loads(evidence)
            assert 'financial' in payload['validation_issue']
            assert 'financial evidence or results are missing' in instruction
            result = schema.model_validate({'slide_index': payload['slide_index'],
                                            'slide': _slide(4)})
            self.last_response_text = result.model_dump_json()
            self.last_route = {'task': task, 'model': self.name}
            return result
        result = super().generate_for_task(task, instruction, evidence, schema, attempt=attempt)
        if task == 'material_pitch_deck':
            changed = result.model_dump()
            changed['slides'][4] = _slide(3)
            result = schema.model_validate(changed)
            self.last_response_text = result.model_dump_json()
        return result


def test_two_bounded_passes_produce_distinct_replayable_decks(tmp_path):
    base = {'input_revision': 'synthetic-revision', 'source_hash': 'source-hash',
            'memo_digest': 'memo-digest', 'sections': SECTIONS}
    (tmp_path / 'material_request.json').write_text(json.dumps({**base, 'digest': digest(base)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    model = FakeLocalModel()
    first = draft_materials(tmp_path, model)
    assert first['state'] == 'needs_resume'
    second = draft_materials(tmp_path, model)
    assert second['state'] == 'accepted'
    assert second['decks']['intro_deck']['sections'] != second['decks']['pitch_deck']['sections']
    assert len(json.loads((tmp_path / 'material_attempts.json').read_text())) == 2
    assert all(len(section) == 4 for section in second['decks']['pitch_deck']['sections'])


def test_slide_source_binding_and_dated_timeline_are_enforced():
    spec = DeckSpec.model_validate({'slides': [_slide(0), _slide(1)]})
    assert render_sections(validate_deck(spec, SECTIONS, 'intro_deck'), SECTIONS)[0][2].startswith('[S1]')
    unbound = spec.model_dump()
    unbound['slides'][0]['body'] = 'Synthetic unsupported assertion with a fabricated source citation [S2] and material unknowns remain.'
    with pytest.raises(ValueError, match='absent'):
        validate_deck(DeckSpec.model_validate(unbound), SECTIONS, 'intro_deck')
    undated = spec.model_dump()
    undated['slides'][0]['layout'] = 'timeline'
    with pytest.raises(ValueError, match='dated'):
        validate_deck(DeckSpec.model_validate(undated), SECTIONS, 'intro_deck')


def test_structured_sentences_bind_numeric_claim_to_selected_source_id():
    sections = [
        ['A', 'Source A reports 2025 activity [S1]. Source B reports 2026 activity [S2].',
         '[S1] Synthetic A\n[S2] Synthetic B'],
        ['B', 'Source B reports 2026 activity [S2].', '[S2] Synthetic B'],
    ]
    slides = [_structured_slide(0), _structured_slide(1)]
    slides[0]['sentences'] = [{'text': 'Synthetic source reports 2026 activity that requires further review before any investment decision is made',
                              'source_ids': ['S1']}]
    spec = StructuredDeckSpec.model_validate({'slides': slides})
    with pytest.raises(ValueError, match='source ID S1; missing 2026'):
        project_structured(spec, sections)
    slides[0]['sentences'][0]['source_ids'] = ['S2']
    projected = project_structured(StructuredDeckSpec.model_validate({'slides': slides}), sections)
    assert projected.slides[0].body.endswith('investment decision is made [S2].')


def test_structured_citation_label_insertion_preserves_authored_sentence_bytes():
    slides = [_structured_slide(0), _structured_slide(1)]
    first = 'The model authored this exact sentence with a period.'
    second = 'The model authored this exact sentence without terminal punctuation'
    slides[0]['sentences'] = [{'text': first, 'source_ids': ['S1']},
                              {'text': second, 'source_ids': ['S1']}]
    spec = StructuredDeckSpec.model_validate({'slides': slides})
    projected = project_structured(spec, SECTIONS)
    assert projected.slides[0].body == (
        'The model authored this exact sentence with a period [S1]. '
        'The model authored this exact sentence without terminal punctuation [S1].')
    assert projected.slides[0].body.replace(' [S1]', '') == first + ' ' + second + '.'
    assert spec.slides[0].sentences[0].text == first
    assert spec.slides[0].sentences[1].text == second


def test_financial_unknown_requires_explicit_same_sentence_and_no_pipeline_leak():
    slides = [_structured_slide(i) for i in range(5)]
    slides[4]['sentences'] = [
        {'text': 'Financial evidence requires review before making any investment decision',
         'source_ids': ['S1']},
        {'text': 'The customer and revenue figures remain unverified until primary records arrive',
         'source_ids': ['S1']}]
    with pytest.raises(ValueError, match='same-sentence disclosure'):
        project_structured(StructuredDeckSpec.model_validate({'slides': slides}), SECTIONS)
    slides[4]['sentences'] = [{'text': 'The allowed numeric values list is empty and financial results are unverified',
                              'source_ids': ['S1']}]
    with pytest.raises(ValueError, match='pipeline instructions'):
        project_structured(StructuredDeckSpec.model_validate({'slides': slides}), SECTIONS)
    slides[4]['sentences'] = [{'text': 'Financial statements are unavailable, so the investment case needs primary records',
                              'source_ids': ['S1']}]
    assert project_structured(StructuredDeckSpec.model_validate({'slides': slides}), SECTIONS)


def test_routed_structured_patch_replaces_frozen_index_without_model_index(tmp_path):
    from agents.research.material_slides import RoutedStructuredSlidePatch
    base = {'input_revision': 'synthetic-revision', 'source_hash': 'source-hash',
            'memo_digest': 'memo-digest', 'sections': SECTIONS}
    request = {**base, 'replay_contracts': {
        'intro_deck': 'structured_v2', 'pitch_deck': 'structured_v2'}}
    (tmp_path / 'material_request.json').write_text(json.dumps({**request,
        'digest': digest(request)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))

    class RoutedModel:
        name = 'qwen3.5:9b'
        last_response_text = ''
        last_route = {}

        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            if task == 'material_intro_deck':
                slides = [_structured_slide(0), _structured_slide(1)]
                slides[1]['purpose'] = 'financial_unknown'
                slides[1]['sentences'][0]['text'] = (
                    'Financial evidence requires review before an investment decision')
                answer = schema.model_validate({'slides': slides})
            else:
                assert task == 'material_intro_deck_patch'
                assert schema is RoutedStructuredSlidePatch
                assert json.loads(evidence)['slide_index'] == 1
                replacement = _structured_slide(4)
                answer = schema.model_validate({'slide': replacement})
            self.last_response_text = answer.model_dump_json()
            self.last_route = {'model': self.name}
            return answer

    model = RoutedModel()
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    rows = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert rows[1]['answer'].keys() == {'slide'}
    replayed = replay_material_rows('intro_deck', {**base, 'kind': 'intro_deck'},
                                    rows, SECTIONS, contract_version='structured_v2')
    assert replayed['state'] == 'accepted'
    assert replayed['authored_spec'].slides[0].heading == 'Synthetic investor point Alpha'
    assert replayed['authored_spec'].slides[1].heading == 'Synthetic investor point Epsilon'


def test_split_memo_citation_and_amount_do_not_bind_but_intact_focus_is_offered():
    sections = [
        ['Split citation', '[S3] Registry filing reports a dated round, with detail continued.',
         '[S3] Synthetic registry'],
        ['Split amount', 'The amount was INR 20 crore in June 2026, with no source tag here.',
         '[S3] Synthetic registry'],
        ['Intact evidence', '[S3] Registry entry reports INR 20 crore in June 2026 with unknown status.',
         '[S3] Synthetic registry'],
        ['Other evidence', 'Synthetic product claim requires primary verification [S1].',
         '[S1] Synthetic product'],
    ]
    first = _structured_slide(0)
    first['sentences'] = [{'text': 'The registry entry reports INR 20 crore in June 2026 with an unknown status requiring verification',
                           'source_ids': ['S3']}]
    second = _structured_slide(1)
    spec = StructuredDeckSpec.model_validate({'slides': [first, second]})
    split_only = [sections[0], sections[1], sections[3]]
    with pytest.raises(ValueError, match='source ID S3.*20 crore'):
        project_structured(spec, split_only)
    projected = project_structured(spec, sections)
    assert projected.slides[0].source_sections == [2]
    payload = {'kind': 'intro_deck', 'input_revision': 'synthetic-revision',
               'source_hash': 'source-hash', 'memo_digest': 'memo-digest',
               'sections': split_only}
    raw = spec.model_dump_json()
    row = {'id': 'response_1', 'task': 'material_intro_deck',
           'instruction': STRUCTURED_SLIDE_INSTRUCTION, 'input': payload,
           'schema': StructuredDeckSpec.model_json_schema(),
           'answer': spec.model_dump(mode='json'), 'raw_response': raw,
           'response_hash': digest(raw), 'model': 'qwen3.5:9b'}
    state = replay_material_rows('intro_deck', payload, [row], split_only,
                                 contract_version='structured')
    assert state['task'] == 'material_intro_deck_patch'
    assert [item['index'] for item in state['payload']['focus_sections']] == [0]
    assert 'revise the model-authored sentence' in state['payload']['correction_goal']


def test_uncited_or_unbound_quantitative_assertions_fail_closed():
    spec = DeckSpec.model_validate({'slides': [_slide(0), _slide(1)]})
    invented = spec.model_dump()
    invented['slides'][0]['body'] = ('Synthetic 2025 revenue of ₹20 million was reported [S1]; '
                                    'the premise remains unverified and needs diligence.')
    with pytest.raises(ValueError, match='quantitative or dated'):
        validate_deck(DeckSpec.model_validate(invented), SECTIONS, 'intro_deck')
    uncited = spec.model_dump()
    uncited['slides'][0]['body'] = ('Synthetic model claim is explicitly illustrative [S1]. '
                                      'The 2025 number is unverified and should be diligenced.')
    dated_sections = [list(section) for section in SECTIONS]
    dated_sections[0][1] += ' The source reports a 2025 date [S1].'
    with pytest.raises(ValueError, match='quantitative slide sentence') as error:
        validate_deck(DeckSpec.model_validate(uncited), dated_sections, 'intro_deck')
    assert 'The 2025 number is unverified' in str(error.value)
    assert 'slide 1' in str(error.value)


def test_invalid_model_deck_receives_bounded_model_correction(tmp_path):
    base = {'input_revision': 'synthetic-revision', 'source_hash': 'source-hash',
            'memo_digest': 'memo-digest', 'sections': SECTIONS}
    (tmp_path / 'material_request.json').write_text(json.dumps({**base, 'digest': digest(base)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    model = CorrectingLocalModel()
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    assert draft_materials(tmp_path, model)['state'] == 'accepted'
    attempts = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert len(attempts) == 3
    assert attempts[1]['input']['previous_response_id'] == attempts[0]['id']
    assert 'quantitative' in attempts[1]['input']['validation_issue']
    assert attempts[1]['task'] == 'material_intro_deck_patch'
    assert attempts[1]['input']['current_deck']['slides'][0] == attempts[0]['answer']['slides'][0]
    assert attempts[1]['input']['current_deck_digest'] == digest(attempts[1]['input']['current_deck'])
    assert attempts[2]['task'] == 'material_pitch_deck'


def test_targeted_patch_replay_rejects_wrong_slide_and_changed_frozen_deck(tmp_path):
    from agents.research.material_slides import replay_material_rows
    base = {'kind': 'intro_deck', 'input_revision': 'synthetic-revision',
            'source_hash': 'source-hash', 'memo_digest': 'memo-digest', 'sections': SECTIONS}
    (tmp_path / 'material_request.json').write_text(json.dumps({**{key: value for key, value in base.items()
        if key != 'kind'}, 'digest': digest({key: value for key, value in base.items()
        if key != 'kind'})}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    model = CorrectingLocalModel()
    draft_materials(tmp_path, model)
    draft_materials(tmp_path, model)
    rows = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert replay_material_rows('intro_deck', base, rows, SECTIONS)['state'] == 'accepted'
    forged = json.loads(json.dumps(rows))
    forged[1]['input']['current_deck']['slides'][0]['body'] = 'Changed outside model response [S1].'
    with pytest.raises(ValueError, match='inputs or correction order'):
        replay_material_rows('intro_deck', base, forged, SECTIONS)


def test_repeating_bad_slide_stops_after_three_model_responses(tmp_path):
    base = {'input_revision': 'synthetic-revision', 'source_hash': 'source-hash',
            'memo_digest': 'memo-digest', 'sections': SECTIONS}
    (tmp_path / 'material_request.json').write_text(json.dumps({**base, 'digest': digest(base)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    model = RepeatingBrokenSlideModel()
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    blocked = draft_materials(tmp_path, model)
    assert blocked == {'state': 'blocked', 'reason': 'intro_deck_model_validation_failed'}
    attempts = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert len(attempts) == 3
    assert [row['task'] for row in attempts] == [
        'material_intro_deck', 'material_intro_deck_patch', 'material_intro_deck_patch']


def test_pitch_financial_unknown_is_model_authored_in_last_slide_patch(tmp_path):
    base = {'input_revision': 'synthetic-revision', 'source_hash': 'source-hash',
            'memo_digest': 'memo-digest', 'sections': SECTIONS}
    (tmp_path / 'material_request.json').write_text(json.dumps({**base, 'digest': digest(base)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    model = FinancialDisclosurePatchModel()
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    accepted = draft_materials(tmp_path, model)
    assert accepted['state'] == 'accepted'
    rows = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert [row['task'] for row in rows] == [
        'material_intro_deck', 'material_pitch_deck', 'material_pitch_deck_patch']
    assert accepted['decks']['pitch_deck']['response_ids'] == ['response_2', 'response_3']
    assert 'financial results are unverified' in accepted['decks']['pitch_deck']['sections'][-1][1]


def test_material_replay_source_requires_exact_memo_model_and_raw_bytes(tmp_path, monkeypatch):
    from scripts import evaluate_local_material_harness as harness
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    prior = tmp_path / 'prior'
    prior.mkdir()
    base = {'input_revision': 'synthetic-revision', 'source_hash': 'source-hash',
            'memo_digest': 'memo-digest', 'sections': SECTIONS}
    (prior / 'material_request.json').write_text(json.dumps({**base, 'digest': digest(base)}))
    (prior / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    (prior / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    (prior / 'result.json').write_text(json.dumps({'state': 'blocked',
        'acceptance_scope': 'public_synthetic_diagnostic_only',
        'investor_material_accepted': False}))
    assert draft_materials(prior, FakeLocalModel())['state'] == 'needs_resume'
    rows, manifest = harness.reusable_intro(prior, base, 'qwen3.5:9b')
    assert len(rows) == 1 and manifest['intro_response_ids'] == ['response_1']
    with pytest.raises(ValueError, match='digest differs'):
        harness.reusable_intro(prior, {**base, 'memo_digest': 'changed'}, 'qwen3.5:9b')
    with pytest.raises(ValueError, match='model differs'):
        harness.reusable_intro(prior, base, 'other:9b')
    attempts_path = prior / 'material_attempts.json'
    saved = attempts_path.read_text()
    tampered = json.loads(saved)
    tampered[0]['raw_response'] = tampered[0]['raw_response'].replace('Synthetic', 'Forged', 1)
    attempts_path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match='modified'):
        harness.reusable_intro(prior, base, 'qwen3.5:9b')
    attempts_path.write_text(saved)


def test_material_gateway_replays_exact_saved_model_sections(tmp_path, monkeypatch):
    from delivery.material_stage import run_material_pass, validate_material_checkpoint

    job = {'input_revision': 'synthetic-revision'}
    memo = {'state': 'accepted', 'source_hash': 'source-hash',
            'sections': SECTIONS, 'recommendation': 'defer_pending_evidence',
            'part_a_response_id': 'a', 'part_b_response_id': 'b',
            'review_response_id': 'review'}
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    monkeypatch.setattr('delivery.material_stage.memo_directory', lambda unused: tmp_path)
    model = FakeLocalModel()

    def fake_private(command, directory, **kwargs):
        result = draft_materials(directory, model)
        (directory / 'material_result.json').write_text(json.dumps(result))

    monkeypatch.setattr('delivery.material_stage.run_private', fake_private)
    assert run_material_pass(job, memo, timeout=100)['state'] == 'needs_resume'
    accepted = run_material_pass(job, memo, timeout=100)
    assert accepted['state'] == 'accepted'
    assert accepted['decks']['intro_deck']['response_id'] == 'response_1'
    assert accepted['decks']['pitch_deck']['response_id'] == 'response_2'
    assert validate_material_checkpoint(job, memo, accepted) == accepted
    changed_memo = {**memo, 'sections': [*SECTIONS, ['Synthetic new finding',
        'New analysis cites [S1].', '[S1] Synthetic fixture']]}
    with pytest.raises(ValueError, match='memo changed'):
        validate_material_checkpoint(job, changed_memo, accepted)
    changed_material = {**accepted, 'decks': {**accepted['decks'],
        'intro_deck': {**accepted['decks']['intro_deck'],
                       'sections': [('Forged claim', 'Unsupported', '', 'statement')]}}}
    with pytest.raises(ValueError, match='checkpoint differs'):
        validate_material_checkpoint(job, memo, changed_material)
    monkeypatch.setattr('delivery.material_stage.run_private', lambda *args, **kwargs: None)
    forged = json.loads((tmp_path / 'material_result.json').read_text())
    forged['decks']['pitch_deck']['sections'][0][1] = 'Manually fabricated investor claim [S1].'
    (tmp_path / 'material_result.json').write_text(json.dumps(forged))
    with pytest.raises(ValueError, match='differs from recorded'):
        run_material_pass(job, memo, timeout=100)


def test_material_gateway_replays_model_authored_slide_patch(tmp_path, monkeypatch):
    from delivery.material_stage import run_material_pass, validate_material_checkpoint

    job = {'input_revision': 'synthetic-revision'}
    memo = {'state': 'accepted', 'source_hash': 'source-hash',
            'sections': SECTIONS, 'recommendation': 'defer_pending_evidence',
            'part_a_response_id': 'a', 'part_b_response_id': 'b',
            'review_response_id': 'review'}
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    monkeypatch.setattr('delivery.material_stage.memo_directory', lambda unused: tmp_path)
    model = CorrectingLocalModel()

    def fake_private(command, directory, **kwargs):
        result = draft_materials(directory, model)
        (directory / 'material_result.json').write_text(json.dumps(result))

    monkeypatch.setattr('delivery.material_stage.run_private', fake_private)
    assert run_material_pass(job, memo, timeout=100)['state'] == 'needs_resume'
    assert run_material_pass(job, memo, timeout=100)['state'] == 'needs_resume'
    accepted = run_material_pass(job, memo, timeout=100)
    assert accepted['decks']['intro_deck']['response_ids'] == ['response_1', 'response_2']
    assert validate_material_checkpoint(job, memo, accepted) == accepted
    attempts_path = tmp_path / 'material_attempts.json'
    attempts = json.loads(attempts_path.read_text())
    attempts[1]['input']['slide_index'] = 1
    attempts_path.write_text(json.dumps(attempts))
    with pytest.raises(ValueError, match='inputs or correction order'):
        validate_material_checkpoint(job, memo, accepted)


def test_invalid_deck_count_gets_bounded_whole_deck_retry(tmp_path):
    base = {'input_revision': 'synthetic-revision', 'source_hash': 'source-hash',
            'memo_digest': 'memo-digest', 'sections': SECTIONS,
            'replay_contracts': {'intro_deck': 'structured_v3',
                                 'pitch_deck': 'structured_v3'}}
    (tmp_path / 'material_request.json').write_text(json.dumps({**base,
        'digest': digest(base)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))

    class CountModel(FakeLocalModel):
        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            payload = json.loads(evidence)
            if task == 'material_intro_deck' and 'validation_issue' not in payload:
                slides = [_structured_slide(index) for index in range(5)] + [
                    _structured_slide(0)]
                result = schema.model_validate({'slides': slides})
                self.last_response_text = result.model_dump_json()
                self.last_route = {'model': self.name}
                return result
            return super().generate_for_task(task, instruction, evidence, schema,
                                             attempt=attempt)

    model = CountModel()
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    retry = draft_materials(tmp_path, model)
    assert retry['state'] == 'needs_resume'
    rows = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert rows[1]['task'] == 'material_intro_deck'
    assert rows[1]['input']['previous_response_id'] == rows[0]['id']
    assert rows[1]['input']['validation_issue'] == (
        'Deck slide count outside its material contract')


def test_deck_kind_is_encoded_in_new_structured_response_schema():
    from agents.research.material_slides import (IntroStructuredDeckSpec,
                                                  PitchStructuredDeckSpec)
    base = {'kind': 'intro_deck', 'sections': SECTIONS}
    intro = replay_material_rows('intro_deck', base, [], SECTIONS,
                                 contract_version='structured_v4')
    pitch = replay_material_rows('pitch_deck', {**base, 'kind': 'pitch_deck'},
                                 [], SECTIONS, contract_version='structured_v4')
    assert intro['schema'] is IntroStructuredDeckSpec
    assert pitch['schema'] is PitchStructuredDeckSpec
    with pytest.raises(ValueError):
        IntroStructuredDeckSpec.model_validate({'slides': [_structured_slide(0)] * 6})
    assert len(PitchStructuredDeckSpec.model_validate({
        'slides': [_structured_slide(index) for index in range(5)]}).slides) == 5


def test_empty_exception_message_is_still_a_failed_recorded_response():
    from agents.inference.model_authorship import response_answer
    row = {'id': 'response_1', 'error': '', 'raw_response': '',
           'response_hash': digest('')}
    with pytest.raises(ValueError, match='No successful model response'):
        response_answer([row], 'response_1')


def test_undated_timeline_uses_evidence_layout_without_changing_model_words():
    slides = [_structured_slide(0, layout='timeline'), _structured_slide(1)]
    authored = StructuredDeckSpec.model_validate({'slides': slides})
    old = project_structured(authored, SECTIONS)
    with pytest.raises(ValueError, match='Timeline layout requires'):
        validate_deck(old, SECTIONS, 'intro_deck')
    projected = project_structured(authored, SECTIONS, layout_fallback=True)
    assert projected.slides[0].layout == 'evidence'
    assert projected.slides[0].body == old.slides[0].body
    assert validate_deck(projected, SECTIONS, 'intro_deck') == projected
