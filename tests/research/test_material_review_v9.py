"""Synthetic review contract that selects exact enumerated sentences."""
import json
from copy import deepcopy

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_review import (
    REVIEW_INSTRUCTION_V8, REVIEW_INSTRUCTION_V9, compact_review_payload,
    project_review, review_instruction, review_schema)
from scripts.private_material_review_worker import review_materials


SECTIONS = [['Synthetic memo',
             'One seed round has unknown status [S1]. Financials are unavailable [S2].',
             '[S1] [S2] Synthetic evidence']]
DECKS = {
    'intro_deck': [['Funding context',
                    'One round is recorded [S1]. All rounds are completed [S1]. '
                    'The team is experienced.', '[S1] evidence', 'evidence']],
    'pitch_deck': [['Financial context', 'Financials are unavailable [S2].',
                    '[S2] evidence', 'evidence']],
}
OPTIONS = {'thinking': False, 'max_tokens': 1200,
           'context_tokens': 16384, 'temperature': 0}


def request(contract='semantic_v9'):
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'material_digest': 'material',
            'memo_sections': SECTIONS, 'decks': DECKS,
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'synthetic-model-digest',
                             'options': OPTIONS}, 'review_contract': contract}
    return {**base, 'digest': digest(base)}


def block(choice='intro_deck.slide_1.sentence_2', memo=0):
    return {'verdict': 'block',
            'rationale': 'The slide presents an unsupported completed funding status.',
            'findings': [{'sentence_choice': choice, 'issue': 'unsupported_claim',
                          'memo_evidence_index': memo,
                          'explanation': 'The memo reports one round with unknown status, not completed rounds.'}]}


def passing():
    return {'verdict': 'pass', 'findings': [],
            'rationale': 'The supplied deck claims align with the cited memo evidence.'}


class FakeReviewModel:
    name = 'qwen3.5:9b'
    last_response_text = ''
    last_route = {}

    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == 'material_semantic_review'
        assert instruction == REVIEW_INSTRUCTION_V9
        answer = self.answers[self.calls]
        self.calls += 1
        result = schema.model_validate(answer)
        self.last_response_text = result.model_dump_json()
        self.last_route = {'model': self.name, **OPTIONS}
        return result


def test_enum_and_payload_are_stable_and_exactly_anchored():
    req = request()
    payload = compact_review_payload(req)
    choices = payload['sentence_choices']
    assert [item['id'] for item in choices] == [
        'intro_deck.slide_1.sentence_1', 'intro_deck.slide_1.sentence_2',
        'intro_deck.slide_1.sentence_3', 'pitch_deck.slide_1.sentence_1']
    assert [item['memo_evidence_indices'] for item in choices] == [[0], [0], [], [1]]
    schema = review_schema(req)
    enum = schema.model_json_schema()['$defs']['MaterialFindingV9Choice'][
        'properties']['sentence_choice']['enum']
    assert enum == [item['id'] for item in choices]
    assert schema.model_json_schema() == review_schema(req).model_json_schema()
    assert review_instruction(req) == REVIEW_INSTRUCTION_V9
    assert review_instruction(request('semantic_v8')) == REVIEW_INSTRUCTION_V8


def test_model_defect_binds_exact_sentence_and_same_source_memo():
    req = request()
    answer = block()
    result = project_review(review_schema(req).model_validate(answer), req)
    finding = result.findings[0]
    assert result.verdict == answer['verdict']
    assert result.rationale == answer['rationale']
    assert finding.issue == answer['findings'][0]['issue']
    assert finding.explanation == answer['findings'][0]['explanation']
    assert finding.deck == 'intro_deck' and finding.slide_index == 0
    assert finding.heading_quote == 'Funding context'
    assert finding.body_quote == 'All rounds are completed [S1].'
    assert finding.memo_quote == 'One seed round has unknown status [S1].'


def test_model_control_pass_has_no_software_generated_findings():
    req = request()
    assert project_review(review_schema(req).model_validate(passing()), req).model_dump() == passing()


def test_split_memo_section_does_not_offer_a_funding_fragment():
    req = request()
    req['decks'] = deepcopy(req['decks'])
    req['decks']['pitch_deck'][0][1] += ' A registry reports a round [S3].'
    req['memo_sections'] = [
        ['Funding A', 'One seed round has unknown status [S1]. Financials are unavailable [S2].\n'
         '[S3] A registry entry reports a Series A ', 'synthetic'],
        ['Funding B', 'round but this is the continuation of the preceding section.\n'
         '[S3] A registry entry reports a Series A round with unknown status.', 'synthetic'],
    ]
    req['digest'] = digest({key: value for key, value in req.items() if key != 'digest'})
    spans = [row['exact_span'] for row in compact_review_payload(req)['memo_evidence']]
    assert '[S3] A registry entry reports a Series A ' not in spans
    assert '[S3] A registry entry reports a Series A round with unknown status.' in spans
    assert all(len(span) > 20 and span.endswith('.') for span in spans)
    req['memo_sections'][1][1] = 'round but this is the continuation of the preceding section.'
    with pytest.raises(ValueError, match='lacks complete memo evidence'):
        compact_review_payload(req)


def test_unoffered_or_wrong_source_choices_fail_closed():
    req = request()
    schema = review_schema(req)
    for invalid in ('intro_deck.slide_1.sentence_4', 'pitch_deck.slide_1.sentence_2',
                    'intro_deck.slide_2.sentence_1'):
        with pytest.raises(ValueError):
            schema.model_validate(block(invalid))
    with pytest.raises(ValueError, match='not offered'):
        project_review(schema.model_validate(block(memo=1)), req)
    with pytest.raises(ValueError, match='null only'):
        project_review(schema.model_validate(block('intro_deck.slide_1.sentence_3', 0)), req)


def test_frozen_v9_defect_and_control_replay_without_inference(tmp_path):
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
