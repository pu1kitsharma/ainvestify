"""Synthetic semantic_v8 tests: memo evidence offered per selected slide sentence."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_review import (MaterialReview, MaterialReviewV5,
    MaterialReviewV6, REVIEW_INSTRUCTION, REVIEW_INSTRUCTION_V2, REVIEW_INSTRUCTION_V3,
    REVIEW_INSTRUCTION_V4, REVIEW_INSTRUCTION_V5, REVIEW_INSTRUCTION_V6,
    REVIEW_INSTRUCTION_V8, compact_review_payload, project_review, review_instruction,
    review_schema)
from scripts.private_material_review_worker import review_materials


SECTIONS = [['Synthetic memo',
             'One seed round has unknown status [S1]. Financials are unavailable [S2].',
             '[S1] [S2] Synthetic evidence']]
DECKS = {
    'intro_deck': [['Funding context',
                    'One round is recorded [S1]. All rounds are completed [S1]. '
                    'The team is experienced.',
                    '[S1] Synthetic evidence', 'evidence']],
    'pitch_deck': [['Financial context', 'Financials are unavailable [S2].',
                    '[S2] Synthetic evidence', 'evidence']],
}
OPTIONS = {'thinking': False, 'max_tokens': 1200,
           'context_tokens': 16384, 'temperature': 0}
S1, S2 = 0, 1  # memo_evidence indices of the two synthetic spans


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


def base_request(contract='semantic_v8'):
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'material_digest': 'material',
            'memo_sections': SECTIONS, 'decks': DECKS,
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'synthetic-model-digest',
                             'options': OPTIONS}}
    if contract:
        base['review_contract'] = contract
    return {**base, 'digest': digest(base)}


def write_request(root, contract='semantic_v8'):
    request = base_request(contract)
    (root / 'material_review_request.json').write_text(json.dumps(request))
    (root / 'material_review_budget.json').write_text(json.dumps({'seconds': 90}))
    return request


def block(sentence, memo, issue='unsupported_claim', deck='intro_deck',
          explanation='The memo reports unknown status for one round, not completed rounds.'):
    return {'verdict': 'block',
            'rationale': 'The slide presents an unsupported completed funding status.',
            'findings': [{'deck': deck, 'slide_index': 0, 'issue': issue,
                          'body_sentence_index': sentence, 'memo_evidence_index': memo,
                          'explanation': explanation}]}


def test_payload_offers_each_sentence_only_spans_sharing_its_source_ids():
    payload = compact_review_payload(base_request())
    assert [span['exact_span'] for span in payload['memo_evidence']] == [
        'One seed round has unknown status [S1].', 'Financials are unavailable [S2].']
    assert payload['sentence_evidence'] == {
        'intro_deck': [[[S1], [S1], []]], 'pitch_deck': [[[S2]]]}
    # Choices line up one-to-one with the sentences the model selects from.
    for kind, slides in payload['slide_sentences'].items():
        assert [len(sentences) for sentences in slides] == [
            len(choices) for choices in payload['sentence_evidence'][kind]]


def test_selected_offered_span_is_bound_and_model_authored_fields_are_untouched():
    request = base_request()
    answer = block(1, S1)
    projected = project_review(MaterialReviewV6.model_validate(answer), request)
    finding = projected.findings[0]
    assert finding.body_quote == 'All rounds are completed [S1].'
    assert finding.heading_quote == 'Funding context'
    assert finding.memo_quote == 'One seed round has unknown status [S1].'
    assert finding.memo_section_index == 0
    # Software binds evidence only: defect, issue and explanation are the model's.
    assert projected.verdict == answer['verdict']
    assert projected.rationale == answer['rationale']
    assert finding.issue == answer['findings'][0]['issue']
    assert finding.explanation == answer['findings'][0]['explanation']


def test_software_never_adds_a_finding_to_a_model_pass():
    answer = {'verdict': 'pass', 'findings': [],
              'rationale': 'The deck claims are aligned with the supplied memo spans.'}
    projected = project_review(MaterialReviewV6.model_validate(answer), base_request())
    assert projected.model_dump(mode='json') == answer


def test_span_from_another_source_is_not_offered_and_is_rejected():
    request = base_request()
    candidate = MaterialReviewV6.model_validate(block(1, S2))
    with pytest.raises(ValueError, match=r'not offered for its slide sentence.*\[0\]'):
        project_review(candidate, request)
    # semantic_v7 offered every span; the same answer keeps its recorded v7 reason.
    with pytest.raises(ValueError, match='unrelated memo source'):
        project_review(candidate, base_request('semantic_v7'))


def test_cited_sentence_needs_an_offered_span_unless_pure_heading_mismatch():
    request = base_request()
    with pytest.raises(ValueError, match=r'lacks a selected memo evidence span.*\[0\]'):
        project_review(MaterialReviewV6.model_validate(block(1, None)), request)
    mismatch = project_review(MaterialReviewV6.model_validate(
        block(1, None, issue='heading_body_mismatch')), request)
    assert mismatch.findings[0].memo_quote is None


def test_uncited_sentence_is_offered_no_span_and_none_is_invented():
    request = base_request()
    uncited = block(2, None,
                    explanation='The sentence asserts team experience without citing any source.')
    projected = project_review(MaterialReviewV6.model_validate(uncited), request)
    finding = projected.findings[0]
    assert finding.body_quote == 'The team is experienced.'
    assert finding.memo_quote is None and finding.memo_section_index is None
    assert finding.issue == 'unsupported_claim'
    with pytest.raises(ValueError, match='not offered for its slide sentence.*null only'):
        project_review(MaterialReviewV6.model_validate(block(2, S1)), request)
    # Earlier contracts still require a span for the same answer.
    with pytest.raises(ValueError, match='lacks a selected memo evidence span'):
        project_review(MaterialReviewV6.model_validate(uncited), base_request('semantic_v7'))


def test_unknown_indices_still_fail_closed():
    request = base_request()
    with pytest.raises(ValueError, match='unknown memo evidence span'):
        project_review(MaterialReviewV6.model_validate(block(1, 9)), request)
    with pytest.raises(ValueError, match='unknown slide sentence'):
        project_review(MaterialReviewV6.model_validate(block(9, S1)), request)


@pytest.mark.parametrize('contract, instruction, schema, extra', [
    (None, REVIEW_INSTRUCTION, MaterialReview, set()),
    ('semantic_v2', REVIEW_INSTRUCTION_V2, MaterialReview, set()),
    ('semantic_v3', REVIEW_INSTRUCTION_V3, MaterialReview, set()),
    ('semantic_v4', REVIEW_INSTRUCTION_V4, MaterialReview, set()),
    ('semantic_v5', REVIEW_INSTRUCTION_V5, MaterialReviewV5, set()),
    ('semantic_v6', REVIEW_INSTRUCTION_V6, MaterialReviewV6, {'slide_sentences'}),
    ('semantic_v7', REVIEW_INSTRUCTION_V6, MaterialReviewV6, {'slide_sentences'}),
    ('semantic_v8', REVIEW_INSTRUCTION_V8, MaterialReviewV6,
     {'slide_sentences', 'sentence_evidence'}),
])
def test_earlier_contracts_keep_their_frozen_instruction_schema_and_payload(
        contract, instruction, schema, extra):
    request = base_request(contract)
    assert review_instruction(request) == instruction
    assert review_schema(request) is schema
    assert set(compact_review_payload(request)) == {
        'input_revision', 'source_hash', 'memo_digest', 'material_digest',
        'review_model', 'decks', 'memo_evidence', 'full_request_digest'} | extra
    assert REVIEW_INSTRUCTION_V8.startswith(REVIEW_INSTRUCTION_V6)
    assert ('sentence_evidence' in review_instruction(request)) == (contract == 'semantic_v8')


def test_recorded_semantic_v7_review_replays_exactly_without_inference(tmp_path):
    write_request(tmp_path, 'semantic_v7')
    first = review_materials(tmp_path, FakeReviewModel([block(1, S1)]))
    assert first['state'] == 'blocked' and first['reason'] == 'model_review_blocked'
    recorded = (tmp_path / 'material_review_attempts.json').read_text()
    assert 'sentence_evidence' not in json.loads(recorded)[0]['input']
    assert review_materials(tmp_path, FakeReviewModel([])) == first
    assert (tmp_path / 'material_review_attempts.json').read_text() == recorded


def test_unoffered_choice_gets_one_retry_naming_the_offered_spans(tmp_path):
    write_request(tmp_path)
    model = FakeReviewModel([block(1, S2), block(1, S1)])
    assert review_materials(tmp_path, model) == {
        'state': 'needs_resume', 'reason': 'material_review_model_validation_failed'}
    result = review_materials(tmp_path, model)
    assert result['state'] == 'blocked' and result['reason'] == 'model_review_blocked'
    assert result['review']['findings'][0]['memo_quote'] == (
        'One seed round has unknown status [S1].')
    rows = json.loads((tmp_path / 'material_review_attempts.json').read_text())
    assert len(rows) == 2 and model.calls == 2
    assert rows[0]['input']['sentence_evidence']['intro_deck'] == [[[S1], [S1], []]]
    assert rows[1]['input']['previous_response_id'] == rows[0]['id']
    assert 'offered memo_evidence_index values: [0]' in rows[1]['input']['validation_issue']
    assert review_materials(tmp_path, FakeReviewModel([])) == result


def test_two_unoffered_choices_block_terminally_without_a_third_call(tmp_path):
    write_request(tmp_path)
    model = FakeReviewModel([block(1, S2), block(1, S2), block(1, S1)])
    assert review_materials(tmp_path, model)['state'] == 'needs_resume'
    terminal = review_materials(tmp_path, model)
    assert terminal == {'state': 'blocked',
                        'reason': 'bounded_material_review_validation_exhausted'}
    assert review_materials(tmp_path, model) == terminal and model.calls == 2
    assert len(json.loads((tmp_path / 'material_review_attempts.json').read_text())) == 2


def test_pass_after_an_unbound_block_is_still_a_block(tmp_path):
    write_request(tmp_path)
    passing = {'verdict': 'pass', 'findings': [],
               'rationale': 'The deck claims are aligned with the supplied memo spans.'}
    model = FakeReviewModel([block(1, S2), passing])
    assert review_materials(tmp_path, model)['state'] == 'needs_resume'
    result = review_materials(tmp_path, model)
    assert result['state'] == 'blocked'
    assert result['reason'] == 'material_review_block_withdrawn_unbound'
