"""A blocking material review that cannot be bound must not be replaced by a pass.

Synthetic decks and memo only; a scripted double stands in for the reviewer.
"""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudgetExceeded
from agents.research.material_review import (REVIEW_INSTRUCTION, REVIEW_INSTRUCTION_V2,
                                             REVIEW_INSTRUCTION_V3, MaterialReview,
                                             reports_block, review_instruction,
                                             unbound_block_withdrawn, validate_review)
from scripts.private_material_review_worker import review_materials

SECTIONS = [['Synthetic memo', 'A registry lists a seed round with unknown status [S1]. '
                               'Financial statements are not supplied [S1].',
             '[S1] Synthetic evidence']]
DECKS = {
    'intro_deck': [['Company overview', 'Synthetic product claim requires primary review [S1].',
                    '[S1] Synthetic evidence', 'statement']],
    'pitch_deck': [['Funding', 'The company closed its seed round and holds the cash [S1].',
                    '[S1] Synthetic evidence', 'evidence']],
}
OPTIONS = {'thinking': False, 'max_tokens': 1200, 'context_tokens': 16384, 'temperature': 0}
PASS = {'verdict': 'pass', 'findings': [],
        'rationale': 'Every heading matches its body and each claim is supported.'}


def finding(**changes):
    return {'deck': 'pitch_deck', 'slide_index': 0, 'issue': 'unsupported_claim',
            'heading_quote': 'Funding',
            'body_quote': 'closed its seed round and holds the cash',
            'memo_section_index': 0, 'memo_quote': 'seed round with unknown status',
            'explanation': 'The slide states a completed round; the registry status is unknown.',
            **changes}


def block(*findings):
    return {'verdict': 'block', 'findings': list(findings),
            'rationale': 'The funding slide overstates what the registry entry reports.'}


# The reviewer found the overclaim but paraphrased the slide instead of quoting it.
UNBOUND = block(finding(body_quote='the company has closed the round and has the money'))
BOUND = block(finding())


class Reviewer:
    """Records the raw answer before schema validation, as the local adapter does."""
    name = 'qwen3.5:9b'

    def __init__(self, answers):
        self.answers, self.calls, self.seen = list(answers), 0, []
        self.last_response_text, self.last_route = '', {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == 'material_semantic_review'
        self.calls += 1
        self.seen.append((instruction, json.loads(evidence)))
        answer = self.answers.pop(0)
        self.last_route = {'model': self.name, **OPTIONS}
        if isinstance(answer, Exception):
            raise answer
        self.last_response_text = json.dumps(answer)
        return schema.model_validate(answer)


def request(root, contract='semantic_v3'):
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'material_digest': 'material',
            'memo_sections': SECTIONS, 'decks': DECKS,
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'synthetic-model-digest',
                             'options': OPTIONS}}
    if contract:
        base['review_contract'] = contract
    full = {**base, 'digest': digest(base)}
    (root / 'material_review_request.json').write_text(json.dumps(full))
    (root / 'material_review_budget.json').write_text(json.dumps({'seconds': 90}))
    return full


def attempts(root):
    return json.loads((root / 'material_review_attempts.json').read_text())


def two_passes(root, answers):
    model = Reviewer(answers)
    first = review_materials(root, model)
    second = review_materials(root, model)
    return first, second, model


def test_unbound_block_followed_by_pass_is_blocked_not_accepted(tmp_path):
    request(tmp_path)
    first, second, model = two_passes(tmp_path, [UNBOUND, PASS])
    assert first == {'state': 'needs_resume', 'reason': 'material_review_model_validation_failed'}
    assert second['state'] == 'blocked'
    assert second['reason'] == 'material_review_block_withdrawn_unbound'
    rows = attempts(tmp_path)
    assert (second['withdrawn_response_id'], second['response_id']) == (rows[0]['id'], rows[1]['id'])
    # Both raw answers are kept; software wrote neither and judged neither on the merits.
    assert rows[0]['answer'] == UNBOUND and rows[1]['answer'] == PASS
    assert all(row['raw_response'] and row['response_hash'] for row in rows)
    assert second['review']['verdict'] == 'pass'
    # The retry was told why, and told not to withdraw the finding.
    instruction, payload = model.seen[1]
    assert instruction == REVIEW_INSTRUCTION_V3 and 'withdrawn blocking finding' in instruction
    assert 'absent from exact slide' in payload['validation_issue']
    assert payload['previous_answer'] == UNBOUND
    # Finite: two recorded calls, and a restart replays the same block without inference.
    idle = Reviewer([])
    assert review_materials(tmp_path, idle) == second and idle.calls == 0
    assert model.calls == 2 and len(rows) == 2


def test_unbound_block_corrected_on_retry_is_an_ordinary_bound_block(tmp_path):
    request(tmp_path)
    first, second, model = two_passes(tmp_path, [UNBOUND, BOUND])
    assert first['state'] == 'needs_resume'
    assert second['state'] == 'blocked' and second['reason'] == 'model_review_blocked'
    assert 'withdrawn_response_id' not in second
    assert second['review']['findings'][0]['body_quote'] == 'closed its seed round and holds the cash'


@pytest.mark.parametrize('first_answer', [
    # Rejected by the schema, not by quote binding: three findings where two are allowed.
    block(finding(), finding(), finding()),
    # A contradictory answer: verdict pass, yet it lists a finding.
    {**PASS, 'findings': [finding()]},
    # A block whose memo quote is not in the supplied evidence.
    block(finding(memo_quote='a sentence that is not in the memo at all')),
])
def test_any_earlier_answer_that_raised_a_finding_cannot_be_erased_by_a_pass(tmp_path, first_answer):
    request(tmp_path)
    first, second, model = two_passes(tmp_path, [first_answer, PASS])
    assert first['state'] == 'needs_resume'
    assert second['state'] == 'blocked'
    assert second['reason'] == 'material_review_block_withdrawn_unbound'
    assert attempts(tmp_path)[0]['answer'] == first_answer


def test_pass_after_a_cancelled_or_clean_first_attempt_is_still_accepted(tmp_path):
    # A cancelled call reported nothing, so the later pass withdraws nothing.
    request(tmp_path)
    cancelled = PreparationBudgetExceeded('Preparation reached its time limit during inference.')
    first, second, model = two_passes(tmp_path, [cancelled, PASS])
    assert first == {'state': 'needs_resume', 'reason': 'material_review_pass_budget_exhausted'}
    assert second['state'] == 'accepted' and second['reason'] is None
    assert attempts(tmp_path)[0].get('answer') is None

    # A first-attempt pass is accepted at once, with one call.
    clean = tmp_path / 'clean'
    clean.mkdir()
    request(clean)
    model = Reviewer([PASS])
    assert review_materials(clean, model)['state'] == 'accepted' and model.calls == 1

    # A rejected first answer that raised no finding does not block a later pass.
    vague = tmp_path / 'vague'
    vague.mkdir()
    request(vague)
    empty_block = {'verdict': 'pass', 'findings': [], 'rationale': 'too short'}
    first, second, _ = two_passes(vague, [empty_block, PASS])
    assert first['state'] == 'needs_resume' and second['state'] == 'accepted'


def test_two_unbound_blocks_exhaust_the_cap_and_never_pass(tmp_path):
    request(tmp_path)
    first, second, model = two_passes(tmp_path, [UNBOUND, UNBOUND])
    assert second == {'state': 'blocked', 'reason': 'material_review_model_validation_failed'}
    idle = Reviewer([])
    assert review_materials(tmp_path, idle) == {
        'state': 'blocked', 'reason': 'bounded_material_review_validation_exhausted'}
    assert idle.calls == 0 and model.calls == 2 and len(attempts(tmp_path)) == 2


@pytest.mark.parametrize('contract, instruction', [
    (None, REVIEW_INSTRUCTION), ('semantic_v2', REVIEW_INSTRUCTION_V2)])
def test_earlier_contracts_replay_exactly_as_recorded(tmp_path, contract, instruction):
    """The guard is versioned. A saved run under an earlier contract keeps its recorded
    instruction, payload and outcome, including the pass this guard would now block."""
    full = request(tmp_path, contract)
    assert review_instruction(full) == instruction
    first, second, model = two_passes(tmp_path, [UNBOUND, PASS])
    assert second['state'] == 'accepted' and 'withdrawn_response_id' not in second
    assert [seen[0] for seen in model.seen] == [instruction, instruction]
    saved = (tmp_path / 'material_review_attempts.json').read_bytes()
    idle = Reviewer([])
    assert review_materials(tmp_path, idle) == second and idle.calls == 0
    assert (tmp_path / 'material_review_attempts.json').read_bytes() == saved
    # The same saved rows cannot be presented under the guarded contract.
    request(tmp_path, 'semantic_v3')
    with pytest.raises(ValueError, match='differs from frozen contract'):
        review_materials(tmp_path, Reviewer([]))


def test_guard_helpers_read_the_raw_answer_and_only_under_the_new_contract():
    assert reports_block(UNBOUND) and reports_block({**PASS, 'findings': [finding()]})
    assert reports_block({'verdict': 'block'}) and not reports_block(PASS)
    assert not reports_block(None) and not reports_block('block') and not reports_block({})
    rows = [{'id': 'response_1', 'answer': UNBOUND}, {'id': 'response_2', 'answer': PASS}]
    assert unbound_block_withdrawn({'review_contract': 'semantic_v3'}, rows) == 'response_1'
    assert unbound_block_withdrawn({'review_contract': 'semantic_v2'}, rows) is None
    assert unbound_block_withdrawn({}, rows) is None
    assert unbound_block_withdrawn({'review_contract': 'semantic_v3'}, rows[1:]) is None
    # The semantic_v2 finding rules still apply under the new contract.
    full = {'decks': DECKS, 'memo_sections': SECTIONS, 'input_revision': 'synthetic',
            'source_hash': 'source', 'memo_digest': 'memo', 'material_digest': 'material',
            'review_model': {'name': 'qwen3.5:9b', 'options': OPTIONS}, 'digest': 'x',
            'review_contract': 'semantic_v3'}
    supports = MaterialReview.model_validate(block(finding(
        explanation='The memo supports this slide statement about the seed round.')))
    with pytest.raises(ValueError, match='says the memo supports the slide'):
        validate_review(supports, full)
    assert validate_review(MaterialReview.model_validate(BOUND), full).verdict == 'block'
