"""Synthetic exact semantic review and finite correction tests."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_review import (MaterialReview, MaterialReviewV5,
    MaterialReviewV6,
    compact_review_payload, project_review, review_instruction, validate_review)
from scripts.private_material_review_worker import review_materials


SECTIONS = [['Synthetic memo', 'Financial statements are not supplied [S1].',
             '[S1] Synthetic evidence']]
DECKS = {
    'intro_deck': [['Company overview', 'Synthetic product claim requires primary review [S1].',
                    '[S1] Synthetic evidence', 'statement']],
    'pitch_deck': [['Financial evidence unknown',
                    'Financial statements are not supplied and remain unverified [S1].',
                    '[S1] Synthetic evidence', 'evidence']],
}
OPTIONS = {'thinking': False, 'max_tokens': 1200,
           'context_tokens': 16384, 'temperature': 0}


class FakeReviewModel:
    name = 'qwen3.5:9b'
    last_response_text = ''
    last_route = {}

    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == 'material_semantic_review'
        answer = self.answers[self.calls]
        self.calls += 1
        result = schema.model_validate(answer)
        self.last_response_text = result.model_dump_json()
        self.last_route = {'model': self.name, **OPTIONS}
        return result


def request(root):
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'material_digest': 'material',
            'memo_sections': SECTIONS, 'decks': DECKS,
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'synthetic-model-digest',
                             'options': OPTIONS}}
    (root / 'material_review_request.json').write_text(json.dumps({**base,
        'digest': digest(base)}))
    (root / 'material_review_budget.json').write_text(json.dumps({'seconds': 90}))
    return base


def test_finding_quotes_must_bind_to_exact_slide_and_memo():
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'material_digest': 'material',
            'decks': DECKS, 'memo_sections': SECTIONS,
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'synthetic-model-digest',
                             'options': OPTIONS}}
    base['digest'] = digest(base)
    good = MaterialReview.model_validate({'verdict': 'block', 'rationale':
        'The pitch should be checked against primary financial evidence.',
        'findings': [{'deck': 'pitch_deck', 'slide_index': 0,
            'issue': 'unsupported_claim', 'heading_quote': 'Financial evidence unknown',
            'body_quote': 'Financial statements are not supplied',
            'memo_section_index': 0, 'memo_quote': 'Financial statements are not supplied',
            'explanation': 'The stated gap needs exact review before release.'}]})
    assert validate_review(good, base) == good
    bad = good.model_copy(deep=True)
    bad.findings[0].memo_quote = 'Never present in the accepted memo'
    with pytest.raises(ValueError, match='absent from accepted memo'):
        validate_review(bad, base)
    bad = good.model_copy(deep=True)
    bad.findings[0].body_quote = 'Never present in slide body'
    with pytest.raises(ValueError, match='absent from exact slide'):
        validate_review(bad, base)


def test_semantic_v2_rejects_disclosed_gap_as_a_blocking_defect():
    base = {'review_contract': 'semantic_v2', 'input_revision': 'synthetic',
            'source_hash': 'source', 'memo_digest': 'memo',
            'material_digest': 'material', 'decks': DECKS,
            'memo_sections': SECTIONS, 'review_model': {'name': 'qwen3.5:9b'}}
    base['digest'] = digest(base)
    finding = {'deck': 'pitch_deck', 'slide_index': 0,
        'issue': 'financial_unknown', 'heading_quote': 'Financial evidence unknown',
        'body_quote': 'Financial statements are not supplied and remain unverified',
        'memo_section_index': 0, 'memo_quote': 'Financial statements are not supplied',
        'explanation': 'The financial gap needs an explicit disclosure before release.'}
    review = MaterialReview.model_validate({'verdict': 'block',
        'rationale': 'The reviewer reports a missing financial disclosure.',
        'findings': [finding]})
    with pytest.raises(ValueError, match='explicit disclosure'):
        validate_review(review, base)
    assert 'A disclosed unknown is not itself a defect' in review_instruction(base)
    legacy = {key: value for key, value in base.items() if key != 'review_contract'}
    assert 'A disclosed unknown is not itself a defect' not in review_instruction(legacy)


def test_semantic_v2_rejects_unrelated_or_corroborating_memo_findings():
    sections = [['Synthetic memo',
                 'Financial statements are not supplied [S2]. The product exists [S1].',
                 '[S1] [S2] Synthetic evidence']]
    decks = {'intro_deck': [['Company overview',
                            'The product exists [S1].', '[S1] evidence', 'statement']],
             'pitch_deck': [['Financial evidence unknown',
                             'Financial statements are not supplied [S2].',
                             '[S2] evidence', 'evidence']]}
    base = {'review_contract': 'semantic_v2', 'input_revision': 'synthetic',
            'source_hash': 'source', 'memo_digest': 'memo',
            'material_digest': 'material', 'decks': decks,
            'memo_sections': sections, 'review_model': {'name': 'qwen3.5:9b'}}
    base['digest'] = digest(base)
    finding = {'deck': 'intro_deck', 'slide_index': 0,
        'issue': 'unsupported_claim', 'heading_quote': 'Company overview',
        'body_quote': 'The product exists [S1].', 'memo_section_index': 0,
        'memo_quote': 'Financial statements are not supplied [S2].',
        'explanation': 'The quoted memo sentence allegedly disputes the slide claim.'}
    review = MaterialReview.model_validate({'verdict': 'block',
        'rationale': 'A material source support problem was reported.',
        'findings': [finding]})
    with pytest.raises(ValueError, match='unrelated memo source'):
        validate_review(review, base)
    review.findings[0].memo_quote = 'The product exists [S1].'
    review.findings[0].explanation = 'The memo supports this slide statement, so block it.'
    with pytest.raises(ValueError, match='supports the slide'):
        validate_review(review, base)


def test_semantic_v4_allows_narrow_source_support_inside_a_broader_dispute():
    decks = {'intro_deck': [['Funding context',
                            'All funding rounds have unknown status [S1].',
                            '[S1] evidence', 'evidence']],
             'pitch_deck': DECKS['pitch_deck']}
    sections = [['Synthetic memo', 'One seed round has unknown status [S1].',
                 '[S1] Synthetic evidence']]
    base = {'review_contract': 'semantic_v4', 'input_revision': 'synthetic',
            'source_hash': 'source', 'memo_digest': 'memo',
            'material_digest': 'material', 'decks': decks,
            'memo_sections': sections, 'review_model': {'name': 'qwen3.5:9b'}}
    base['digest'] = digest(base)
    finding = {'deck': 'intro_deck', 'slide_index': 0,
        'issue': 'unsupported_claim', 'heading_quote': 'Funding context',
        'body_quote': 'All funding rounds have unknown status [S1].',
        'memo_section_index': 0, 'memo_quote': 'One seed round has unknown status [S1].',
        'explanation': 'The memo supports one seed round, but the slide extends it to all rounds.'}
    review = MaterialReview.model_validate({'verdict': 'block',
        'rationale': 'The slide generalizes beyond the cited single round.',
        'findings': [finding]})
    assert validate_review(review, base) == review
    old = {**base, 'review_contract': 'semantic_v3'}
    with pytest.raises(ValueError, match='supports the slide'):
        validate_review(review, old)
    review.findings[0].explanation = 'The memo supports the slide claim completely.'
    with pytest.raises(ValueError, match='supports the slide'):
        validate_review(review, base)


def test_semantic_v5_binds_selected_exact_memo_span_and_rejects_wrong_source():
    sections = [['Synthetic memo',
                 'One seed round has unknown status [S1]. Financials are unavailable [S2].',
                 '[S1] [S2] evidence']]
    decks = {'intro_deck': [['Funding context',
                            'All funding rounds have unknown status [S1].',
                            '[S1] evidence', 'evidence']],
             'pitch_deck': [['Financial context',
                            'Financials are unavailable [S2].',
                            '[S2] evidence', 'evidence']]}
    base = {'review_contract': 'semantic_v5', 'input_revision': 'synthetic',
            'source_hash': 'source', 'memo_digest': 'memo',
            'material_digest': 'material', 'decks': decks,
            'memo_sections': sections, 'review_model': {'name': 'qwen3.5:9b'}}
    base['digest'] = digest(base)
    spans = compact_review_payload(base)['memo_evidence']
    correct = next(i for i, span in enumerate(spans) if '[S1]' in span['exact_span'])
    wrong = next(i for i, span in enumerate(spans) if '[S2]' in span['exact_span'])
    finding = {'deck': 'intro_deck', 'slide_index': 0,
        'issue': 'unsupported_claim', 'heading_quote': 'Funding context',
        'body_quote': 'All funding rounds have unknown status [S1].',
        'memo_evidence_index': correct,
        'explanation': 'The memo supports one round while the slide claims all rounds.'}
    candidate = MaterialReviewV5.model_validate({'verdict': 'block',
        'rationale': 'The slide generalizes beyond the cited single round.',
        'findings': [finding]})
    projected = project_review(candidate, base)
    assert projected.findings[0].memo_quote == spans[correct]['exact_span']
    candidate.findings[0].memo_evidence_index = wrong
    with pytest.raises(ValueError, match='unrelated memo source'):
        project_review(candidate, base)


def test_semantic_v6_binds_exact_slide_sentence_and_memo_span():
    sections = [['Synthetic memo', 'One seed round has unknown status [S1].',
                 '[S1] evidence']]
    decks = {'intro_deck': [['Funding context',
                            'One round is recorded [S1]. All rounds are completed [S1].',
                            '[S1] evidence', 'evidence']],
             'pitch_deck': DECKS['pitch_deck']}
    base = {'review_contract': 'semantic_v6', 'input_revision': 'synthetic',
            'source_hash': 'source', 'memo_digest': 'memo',
            'material_digest': 'material', 'decks': decks,
            'memo_sections': sections, 'review_model': {'name': 'qwen3.5:9b'}}
    base['digest'] = digest(base)
    payload = compact_review_payload(base)
    assert payload['slide_sentences']['intro_deck'][0][1] == 'All rounds are completed [S1].'
    candidate = MaterialReviewV6.model_validate({'verdict': 'block',
        'rationale': 'The slide presents an unsupported completed funding status.',
        'findings': [{'deck': 'intro_deck', 'slide_index': 0,
            'issue': 'unsupported_claim', 'body_sentence_index': 1,
            'memo_evidence_index': 0,
            'explanation': 'The memo reports unknown status for one round, not completed rounds.'}]})
    projected = project_review(candidate, base)
    assert projected.findings[0].heading_quote == 'Funding context'
    assert projected.findings[0].body_quote == 'All rounds are completed [S1].'
    assert projected.findings[0].memo_quote == payload['memo_evidence'][0]['exact_span']
    candidate.findings[0].body_sentence_index = 2
    with pytest.raises(ValueError, match='unknown slide sentence'):
        project_review(candidate, base)


def test_review_pass_and_block_are_recorded_without_extra_calls(tmp_path):
    request(tmp_path)
    pass_answer = {'verdict': 'pass', 'findings': [],
                   'rationale': 'The deck claims are internally aligned with the accepted memo.'}
    model = FakeReviewModel([pass_answer])
    accepted = review_materials(tmp_path, model)
    assert accepted['state'] == 'accepted' and model.calls == 1
    assert review_materials(tmp_path, FakeReviewModel([])) == accepted
    attempts = json.loads((tmp_path / 'material_review_attempts.json').read_text())
    attempts[0]['raw_response'] = attempts[0]['raw_response'].replace('aligned', 'forged')
    (tmp_path / 'material_review_attempts.json').write_text(json.dumps(attempts))
    with pytest.raises(ValueError, match='modified'):
        review_materials(tmp_path, FakeReviewModel([]))


def test_invalid_quote_gets_one_bounded_retry_then_blocks(tmp_path):
    request(tmp_path)
    answer = {'verdict': 'block', 'rationale':
        'The deck contains a source issue that must be reviewed.',
        'findings': [{'deck': 'intro_deck', 'slide_index': 0,
            'issue': 'unsupported_claim', 'heading_quote': 'Company overview',
            'body_quote': 'A quote absent from the slide body',
            'memo_section_index': 0, 'memo_quote': 'Financial statements are not supplied',
            'explanation': 'This finding should fail exact quote validation.'}]}
    model = FakeReviewModel([answer, answer])
    assert review_materials(tmp_path, model)['state'] == 'needs_resume'
    result = review_materials(tmp_path, model)
    assert result['state'] == 'blocked' and model.calls == 2
    rows = json.loads((tmp_path / 'material_review_attempts.json').read_text())
    assert rows[1]['input']['previous_response_id'] == rows[0]['id']
    assert len(rows) == 2


def test_semantic_v7_terminal_validation_block_replays_identically(tmp_path):
    base = request(tmp_path)
    base['review_contract'] = 'semantic_v7'
    (tmp_path / 'material_review_request.json').write_text(json.dumps({**base,
        'digest': digest(base)}))
    answer = {'verdict': 'block', 'rationale':
        'The funding claim requires a source that supports completion.',
        'findings': [{'deck': 'intro_deck', 'slide_index': 0,
            'issue': 'unsupported_claim', 'body_sentence_index': 9,
            'memo_evidence_index': 0,
            'explanation': 'The unavailable sentence must remain a recorded validation failure.'}]}
    model = FakeReviewModel([answer, answer])
    assert review_materials(tmp_path, model)['state'] == 'needs_resume'
    terminal = review_materials(tmp_path, model)
    assert terminal == {'state': 'blocked',
                        'reason': 'bounded_material_review_validation_exhausted'}
    assert review_materials(tmp_path, FakeReviewModel([])) == terminal


def test_private_review_gateway_replays_exact_model_and_deck(tmp_path, monkeypatch):
    from delivery import material_review_stage as stage
    job = {'input_revision': 'synthetic'}
    memo = {'source_hash': 'source', 'sections': SECTIONS}
    material = {'state': 'accepted', 'source_hash': 'source',
                'memo_digest': 'memo', 'decks': {
                    kind: {'sections': rows} for kind, rows in DECKS.items()}}
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {
        'draft': 'qwen3.5:9b', 'review': 'qwen3.5:9b'}}))
    monkeypatch.setattr(stage, 'memo_directory', lambda unused: tmp_path)
    monkeypatch.setattr(stage, 'validate_material_checkpoint',
                        lambda unused_job, unused_memo, exact: exact)
    monkeypatch.setattr(stage, '_installed_digest', lambda name: 'synthetic-model-digest')
    model = FakeReviewModel([{'verdict': 'pass', 'findings': [],
        'rationale': 'The model review found no material mismatch in this synthetic fixture.'}])

    def fake_private(command, root, **kwargs):
        result = review_materials(root, model)
        (root / 'material_review_result.json').write_text(json.dumps(result))

    monkeypatch.setattr(stage, 'run_private', fake_private)
    accepted = stage.run_material_review_pass(job, memo, material, timeout=100)
    assert accepted['state'] == 'accepted' and model.calls == 1
    assert json.loads((tmp_path / 'material_review_request.json').read_text())[
        'review_contract'] == 'semantic_v10'
    assert stage.validate_material_review_checkpoint(job, memo, material, accepted) == accepted
    changed = {**material, 'decks': {**material['decks'],
        'pitch_deck': {'sections': [['Changed heading', *DECKS['pitch_deck'][0][1:]]]}}}
    with pytest.raises(ValueError, match='frozen memo, deck, or model changed'):
        stage.validate_material_review_checkpoint(job, memo, changed, accepted)


@pytest.mark.parametrize('repair_state', ['accepted', 'disputed_without_change'])
def test_repaired_deck_gets_separate_frozen_re_review(tmp_path, monkeypatch,
                                                      repair_state):
    from delivery import material_review_stage as stage
    from delivery import material_repair_stage as repair_stage
    job = {'input_revision': 'synthetic'}
    memo = {'source_hash': 'source', 'sections': SECTIONS}
    repaired = {'state': repair_state, 'memo_digest': 'memo', 'decks': {
        kind: {'sections': rows} for kind, rows in DECKS.items()}}
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {
        'draft': 'qwen3.5:9b', 'review': 'qwen3.5:9b'}}))
    monkeypatch.setattr(stage, 'memo_directory', lambda unused: tmp_path)
    monkeypatch.setattr(repair_stage, 'validate_material_repair_checkpoint',
                        lambda unused_job, unused_memo, exact: exact)
    monkeypatch.setattr(stage, '_installed_digest', lambda name: 'synthetic-model-digest')
    model = FakeReviewModel([{'verdict': 'pass', 'findings': [],
        'rationale': 'The repaired synthetic deck now matches the exact memo evidence.'}])

    def fake_private(command, root, **kwargs):
        result = review_materials(root, model)
        (root / 'material_review_result.json').write_text(json.dumps(result))

    monkeypatch.setattr(stage, 'run_private', fake_private)
    accepted = stage.run_material_review_pass(job, memo, repaired,
                                              timeout=100, repaired=True)
    assert accepted['state'] == 'accepted' and model.calls == 1
    assert (tmp_path / 'material_re_review' / 'material_review_attempts.json').exists()
    assert not (tmp_path / 'material_review_attempts.json').exists()
    assert stage.validate_material_review_checkpoint(job, memo, repaired,
        accepted, repaired=True) == accepted
    changed = {**repaired, 'decks': {**repaired['decks'],
        'pitch_deck': {'sections': [['Changed heading', *DECKS['pitch_deck'][0][1:]]]}}}
    with pytest.raises(ValueError, match='frozen memo, deck, or model changed'):
        stage.validate_material_review_checkpoint(job, memo, changed,
            accepted, repaired=True)
