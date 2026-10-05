"""Synthetic semantic_v10 exact-proposition and complete offered-evidence contract."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_review import (
    REVIEW_INSTRUCTION_V10, compact_review_payload, project_review,
    review_instruction, review_schema)
from scripts.private_material_review_worker import review_materials


SECTIONS = [
    ['Synthetic funding detail',
     'A registry lists one seed round with unknown status [S1]. '
     'The registry amount is unverified [S1]. '
     'Financials are unavailable [S2].', '[S1] [S2] evidence'],
    ['Synthetic aggregate diligence question',
     "All supplied entries have status 'unknown'. Completeness of company history is not established.",
     ''],
]
DECKS = {
    'intro_deck': [['Funding context',
                    'A registry reports a seed round with unknown status [S1]. '
                    'The company received all seed funds [S1].',
                    '[S1] evidence', 'evidence']],
    'pitch_deck': [['Financial context', 'Financials are unavailable [S2].',
                    '[S2] evidence', 'evidence']],
}
OPTIONS = {'thinking': False, 'max_tokens': 1200,
           'context_tokens': 16384, 'temperature': 0}


def request(contract='semantic_v10'):
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'material_digest': 'material',
            'memo_sections': SECTIONS, 'decks': DECKS,
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'synthetic-model-digest',
                             'options': OPTIONS}, 'review_contract': contract}
    return {**base, 'digest': digest(base)}


def block(choice='intro_deck.slide_1.sentence_2',
          proposition='The company received all seed funds'):
    return {'verdict': 'block',
            'rationale': 'The deck asserts funding receipt that the cited registry does not establish.',
            'findings': [{'sentence_choice': choice, 'issue': 'unsupported_claim',
                          'unsupported_proposition': proposition,
                          'explanation': 'A registry listing with unknown status does not establish receipt of funds.'}]}


def passing():
    return {'verdict': 'pass', 'findings': [],
            'rationale': 'The deck attributes registry entries and discloses the evidence gaps.'}


class FakeReviewModel:
    name = 'qwen3.5:9b'
    last_response_text = ''
    last_route = {}

    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == 'material_semantic_review'
        assert instruction == REVIEW_INSTRUCTION_V10
        answer = self.answers[self.calls]
        self.calls += 1
        result = schema.model_validate(answer)
        self.last_response_text = result.model_dump_json()
        self.last_route = {'model': self.name, **OPTIONS}
        return result


def test_schema_and_payload_expose_exact_choice_source_set_and_aggregate_context():
    req = request()
    payload = compact_review_payload(req)
    assert payload['evidence_scope']['supplied_source_ids'] == ['[S1]', '[S2]']
    assert payload['evidence_scope']['company_history_completeness'] == 'unknown'
    assert payload['evidence_scope']['aggregate_memo_sentences'] == [
        {'section_index': 1, 'exact_span': "All supplied entries have status 'unknown'."}]
    assert [item['id'] for item in payload['sentence_choices']] == [
        'intro_deck.slide_1.sentence_1', 'intro_deck.slide_1.sentence_2',
        'pitch_deck.slide_1.sentence_1']
    assert payload['sentence_choices'][1]['memo_evidence_indices'] == [0, 2]
    schema = review_schema(req)
    props = schema.model_json_schema()['$defs']['MaterialFindingV10Choice']['properties']
    assert props['sentence_choice']['enum'] == [item['id'] for item in payload['sentence_choices']]
    assert 'unsupported_proposition' in props and 'memo_evidence_index' not in props
    assert schema.model_json_schema() == review_schema(req).model_json_schema()
    assert review_instruction(req) == REVIEW_INSTRUCTION_V10


def test_model_authored_defect_binds_all_same_source_spans_with_provenance():
    req = request()
    answer = block()
    result = project_review(review_schema(req).model_validate(answer), req)
    finding = result.findings[0]
    assert result.verdict == answer['verdict']
    assert result.rationale == answer['rationale']
    assert finding.issue == answer['findings'][0]['issue']
    assert finding.explanation == answer['findings'][0]['explanation']
    assert finding.unsupported_proposition == answer['findings'][0]['unsupported_proposition']
    assert finding.deck == 'intro_deck' and finding.slide_index == 0
    assert finding.body_quote == 'The company received all seed funds [S1].'
    assert [(item.index, item.section_index, item.exact_span) for item in finding.memo_evidence] == [
        (0, 0, 'A registry lists one seed round with unknown status [S1].'),
        (2, 0, 'The registry amount is unverified [S1].')]
    assert finding.memo_quote == finding.memo_evidence[0].exact_span


def test_control_pass_and_no_deterministic_semantic_override():
    req = request()
    result = project_review(review_schema(req).model_validate(passing()), req)
    assert result.verdict == 'pass' and result.findings == []
    # Software checks exact binding, not whether this model judgment is correct.
    attributed = block('intro_deck.slide_1.sentence_1',
                       'A registry reports a seed round with unknown status')
    assert project_review(review_schema(req).model_validate(attributed), req).verdict == 'block'


def test_invalid_choice_proposition_and_legacy_memo_index_fail_closed():
    req = request()
    schema = review_schema(req)
    with pytest.raises(ValueError):
        schema.model_validate(block('intro_deck.slide_1.sentence_3'))
    with pytest.raises(ValueError, match='absent from exact slide sentence'):
        project_review(schema.model_validate(block(proposition='funds were transferred')), req)
    old = block()
    old['findings'][0]['memo_evidence_index'] = 0
    with pytest.raises(ValueError):
        schema.model_validate(old)


def test_long_complete_source_and_aggregate_spans_remain_exact():
    req = request()
    source_span = 'A registry reports ' + ('verification context ' * 16) + 'unknown status [S1].'
    aggregate_span = 'All supplied entries require ' + ('separate verification ' * 16) + 'before completion.'
    req['memo_sections'] = [
        ['Long source', source_span, '[S1] evidence'],
        ['Long aggregate', aggregate_span, ''],
        ['Financial gap', 'Financial statements are unavailable [S2].', '[S2] evidence']]
    req['digest'] = digest({key: value for key, value in req.items() if key != 'digest'})
    payload = compact_review_payload(req)
    assert len(source_span) > 300 and len(aggregate_span) > 300
    assert payload['memo_evidence'][0]['exact_span'] == source_span
    assert payload['evidence_scope']['aggregate_memo_sentences'][0]['exact_span'] == aggregate_span
    bound = project_review(review_schema(req).model_validate(block()), req)
    assert bound.findings[0].memo_evidence[0].exact_span == source_span


def test_v10_defect_and_control_replay_without_inference(tmp_path):
    for name, answer, expected in [('defect', block(), 'blocked'),
                                    ('control', passing(), 'accepted')]:
        root = tmp_path / name
        root.mkdir()
        (root / 'material_review_request.json').write_text(json.dumps(request()))
        (root / 'material_review_budget.json').write_text(json.dumps({'seconds': 90}))
        model = FakeReviewModel([answer])
        first = review_materials(root, model)
        assert first['state'] == expected and model.calls == 1
        saved = (root / 'material_review_attempts.json').read_bytes()
        assert review_materials(root, FakeReviewModel([])) == first
        assert (root / 'material_review_attempts.json').read_bytes() == saved
