"""Producer and diagnostic-harness wiring for the material review contract.

Synthetic decks and memo only; scripted doubles stand in for the local reviewer.
"""
import hashlib
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_review import REVIEW_INSTRUCTION_V10, review_instruction
from delivery import material_review_stage as stage
from scripts import evaluate_local_material_repair_harness as repair_harness
from scripts import evaluate_local_material_review_harness as review_harness
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
OPTIONS = {'thinking': False, 'max_tokens': 1200, 'context_tokens': 16384, 'temperature': 0}
PASS = {'verdict': 'pass', 'findings': [],
        'rationale': 'The supplied deck claims align with the cited memo evidence.'}
BLOCK = {'verdict': 'block',
         'rationale': 'The slide presents an unsupported completed funding status.',
         'findings': [{'sentence_choice': 'intro_deck.slide_1.sentence_2',
                       'issue': 'unsupported_claim',
                       'unsupported_proposition': 'All rounds are completed',
                       'explanation': 'The memo reports one round with unknown status, not '
                                      'completed rounds.'}]}
RECORDED = (None, 'semantic_v2', 'semantic_v3', 'semantic_v4', 'semantic_v5', 'semantic_v6',
            'semantic_v7', 'semantic_v8', 'semantic_v9')
FRESH = 'semantic_v10'
# The contract the behaviour tests run under: the fresh one, which the review
# module implements.
IMPLEMENTED = FRESH
from agents.research.material_review import REVIEW_INSTRUCTION
V10_IMPLEMENTED = review_instruction({'review_contract': FRESH}) != REVIEW_INSTRUCTION


class Reviewer:
    def __init__(self, answers, name='qwen3.5:9b'):
        self.answers, self.calls, self.name = list(answers), 0, name
        self.instructions, self.last_response_text, self.last_route = [], '', {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == 'material_semantic_review'
        self.calls += 1
        self.instructions.append(instruction)
        self.last_route = {'model': self.name, **OPTIONS}
        self.last_response_text = json.dumps(self.answers.pop(0))
        return schema.model_validate_json(self.last_response_text)


# ---- production stage --------------------------------------------------------------------

@pytest.fixture
def production(tmp_path, monkeypatch):
    """The stage with its private launcher replaced by an in-process worker call."""
    from delivery import material_repair_stage
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {
        'draft': 'qwen3.5:9b', 'review': 'qwen3.5:9b'}}))
    monkeypatch.setattr(stage, 'memo_directory', lambda unused: tmp_path)
    monkeypatch.setattr(stage, 'validate_material_checkpoint', lambda job, memo, exact: exact)
    monkeypatch.setattr(material_repair_stage, 'validate_material_repair_checkpoint',
                        lambda job, memo, exact: exact)
    monkeypatch.setattr(stage, '_installed_digest', lambda name: 'synthetic-model-digest')
    monkeypatch.setattr(stage, 'FRESH_REVIEW_CONTRACT', IMPLEMENTED)
    box = {'model': Reviewer([])}

    def fake_private(command, root, **kwargs):
        (root / 'material_review_result.json').write_text(json.dumps(
            review_materials(root, box['model'])))

    monkeypatch.setattr(stage, 'run_private', fake_private)
    job = {'input_revision': 'synthetic'}
    memo = {'source_hash': 'source', 'sections': SECTIONS}
    material = {'state': 'accepted', 'source_hash': 'source', 'memo_digest': 'memo',
                'decks': {kind: {'sections': rows} for kind, rows in DECKS.items()}}
    return tmp_path, job, memo, material, box


@pytest.mark.parametrize('repaired', [False, True])
def test_fresh_review_and_fresh_re_review_are_frozen_under_the_fresh_contract(production,
                                                                             repaired):
    root, job, memo, material, box = production
    box['model'] = Reviewer([BLOCK])
    result = stage.run_material_review_pass(job, memo, material, timeout=100, repaired=repaired)
    where = root / 'material_re_review' if repaired else root
    request = json.loads((where / 'material_review_request.json').read_text())
    assert request['review_contract'] == stage.FRESH_REVIEW_CONTRACT == IMPLEMENTED
    assert request['digest'] == digest({k: v for k, v in request.items() if k != 'digest'})
    assert box['model'].instructions == [REVIEW_INSTRUCTION_V10] and box['model'].calls == 1
    # The model chose a sentence; software bound the exact slide and memo text.
    assert result['state'] == 'blocked' and result['request_digest'] == request['digest']
    bound = result['review']['findings'][0]
    assert (bound['deck'], bound['slide_index']) == ('intro_deck', 0)
    assert bound['body_quote'] == 'All rounds are completed [S1].'
    assert bound['memo_quote'] in SECTIONS[0][1]
    assert bound['unsupported_proposition'] == 'All rounds are completed'
    # The checkpoint replays the saved response without inference.
    box['model'] = Reviewer([])
    assert stage.validate_material_review_checkpoint(
        job, memo, material, result, expected_state='blocked', repaired=repaired) == result
    assert (root / 'material_review_attempts.json').exists() is not repaired


def test_fresh_v9_pass_is_accepted_and_bound_to_the_exact_deck(production):
    root, job, memo, material, box = production
    box['model'] = Reviewer([PASS])
    accepted = stage.run_material_review_pass(job, memo, material, timeout=100)
    assert accepted['state'] == 'accepted' and box['model'].calls == 1
    box['model'] = Reviewer([])
    assert stage.validate_material_review_checkpoint(job, memo, material, accepted) == accepted
    changed = {**material, 'decks': {**material['decks'], 'pitch_deck': {
        'sections': [['Changed heading', *DECKS['pitch_deck'][0][1:]]]}}}
    with pytest.raises(ValueError, match='frozen memo, deck, or model changed'):
        stage.validate_material_review_checkpoint(job, memo, changed, accepted)


@pytest.mark.parametrize('contract', RECORDED)
@pytest.mark.parametrize('repaired', [False, True])
def test_recorded_v1_to_v9_request_replays_exactly_and_is_never_upgraded(production, contract,
                                                                         repaired, monkeypatch):
    root, job, memo, material, box = production
    # The production default: whatever is recorded must replay under its own contract.
    monkeypatch.setattr(stage, 'FRESH_REVIEW_CONTRACT', FRESH)
    where = root / 'material_re_review' if repaired else root
    where.mkdir(exist_ok=True)
    # A request recorded under an earlier contract, with its response.
    recorded = stage._review_request(job, memo, material, root, repaired=repaired,
                                     review_contract=contract)
    assert recorded.get('review_contract') == contract and ('review_contract' in recorded) == (
        contract is not None)
    path = where / 'material_review_request.json'
    path.write_text(json.dumps(recorded, ensure_ascii=False))
    box['model'] = Reviewer([PASS])
    accepted = stage.run_material_review_pass(job, memo, material, timeout=100,
                                              repaired=repaired)
    assert accepted['state'] == 'accepted'
    assert box['model'].instructions == [review_instruction(recorded)]
    assert json.loads((where / 'material_review_request.json').read_text()).get(
        'review_contract') == contract != FRESH
    saved = {name: (where / name).read_bytes() for name in (
        'material_review_request.json', 'material_review_attempts.json',
        'material_review_result.json')}
    assert json.loads(saved['material_review_request.json']) == recorded     # not upgraded
    # A later pass and the checkpoint replay it exactly, with no inference.
    box['model'] = Reviewer([])
    assert stage.run_material_review_pass(job, memo, material, timeout=100,
                                          repaired=repaired) == accepted
    assert stage.validate_material_review_checkpoint(job, memo, material, accepted,
                                                     repaired=repaired) == accepted
    assert box['model'].calls == 0
    assert {name: (where / name).read_bytes() for name in saved} == saved


def test_unknown_recorded_contract_is_refused_and_v9_is_itself_replayable(production):
    root, job, memo, material, box = production
    assert stage._recorded_review_contract(root / 'absent.json') == IMPLEMENTED
    assert set(RECORDED) | {FRESH, 'semantic_v12', 'semantic_v13'} == set(
        stage.RECORDED_REVIEW_CONTRACTS)
    path = root / 'material_review_request.json'
    path.write_text(json.dumps({'review_contract': 'semantic_v99'}))
    with pytest.raises(ValueError, match='Unknown recorded material review contract'):
        stage.run_material_review_pass(job, memo, material, timeout=100)
    path.write_text(json.dumps({'review_contract': 'semantic_v9'}))
    assert stage._recorded_review_contract(path) == 'semantic_v9'


def test_production_pass_keeps_the_time_budget_and_makes_no_extra_call(production):
    root, job, memo, material, box = production
    box['model'] = Reviewer([PASS])
    stage.run_material_review_pass(job, memo, material, timeout=60)
    assert json.loads((root / 'material_review_budget.json').read_text()) == {'seconds': 52}
    stage.run_material_review_pass(job, memo, material, timeout=400)
    assert json.loads((root / 'material_review_budget.json').read_text()) == {'seconds': 105}
    assert box['model'].calls == 1


def test_fresh_contract_is_semantic_v10_and_is_never_a_silent_fallback(production, tmp_path,
                                                                        monkeypatch):
    """Fresh requests are v10 everywhere. Until the review module implements it, a
    producer refuses to create a request instead of running the unversioned contract."""
    from scripts import evaluate_local_material_review_pair as pair_harness
    root, job, memo, material, box = production
    monkeypatch.setattr(stage, 'FRESH_REVIEW_CONTRACT', FRESH)
    assert (stage.FRESH_REVIEW_CONTRACT == review_harness.FRESH_REVIEW_CONTRACT ==
            repair_harness.FRESH_REVIEW_CONTRACT == pair_harness.FRESH_REVIEW_CONTRACT == FRESH)
    for guard in (stage.require_supported_contract, review_harness.require_supported_contract):
        assert guard(IMPLEMENTED) == IMPLEMENTED and guard(None) is None
        with pytest.raises(ValueError, match='does not implement semantic_v99'):
            guard('semantic_v99')
    box['model'] = Reviewer([PASS])
    base = {'input_revision': 'synthetic-r1', 'review_model': {'name': 'local'}}
    if V10_IMPLEMENTED:
        accepted = stage.run_material_review_pass(job, memo, material, timeout=100)
        request = json.loads((root / 'material_review_request.json').read_text())
        assert request['review_contract'] == FRESH and accepted['state'] == 'accepted'
        assert repair_harness._re_review_request(base)['review_contract'] == FRESH
    else:
        for repaired in (False, True):
            with pytest.raises(ValueError, match='does not implement semantic_v10'):
                stage.run_material_review_pass(job, memo, material, timeout=100,
                                               repaired=repaired)
        with pytest.raises(ValueError, match='does not implement semantic_v10'):
            repair_harness._re_review_request(base)
        # Nothing was frozen and nothing was asked of the model.
        assert not (root / 'material_review_request.json').exists()
        assert not (root / 'material_re_review' / 'material_review_request.json').exists()
        assert box['model'].calls == 0


# ---- repair diagnostic harness --------------------------------------------------------------

def test_repair_harness_re_review_is_fresh_and_recorded_reviews_keep_their_contract(monkeypatch):
    base = {'input_revision': 'synthetic-r1', 'review_model': {'name': 'local'}}
    monkeypatch.setattr(repair_harness, 'FRESH_REVIEW_CONTRACT', IMPLEMENTED)
    fresh = repair_harness._re_review_request(base)
    assert fresh['review_contract'] == repair_harness.FRESH_REVIEW_CONTRACT == IMPLEMENTED
    assert fresh['digest'] == digest({k: v for k, v in fresh.items() if k != 'digest'})
    assert 'review_contract' not in base
    for contract in (*RECORDED, FRESH):
        versioned = base if contract is None else {**base, 'review_contract': contract}
        recorded = {**versioned, 'digest': digest(versioned)}
        assert repair_harness._bound_review_request(base, recorded) == recorded
        assert ('review_contract' in recorded) == (contract is not None)


# ---- review diagnostic harness ----------------------------------------------------------------

INSTALLED = {'qwen3.5:9b': 'sha256:nine', 'qwen3:14b': 'sha256:fourteen'}


def test_review_pin_defaults_to_the_draft_model_or_an_installed_local_override(tmp_path):
    pin, record = review_harness.review_pin('qwen3.5:9b', None, INSTALLED, tmp_path / 'run-1')
    assert pin == {'name': 'qwen3.5:9b', 'digest': 'sha256:nine', 'options': OPTIONS}
    assert record['source'] == 'material_profile_draft'
    pin, record = review_harness.review_pin('qwen3.5:9b', 'qwen3:14b', INSTALLED,
                                            tmp_path / '2026-10-04-qwen3-14b-review')
    assert pin == {'name': 'qwen3:14b', 'digest': 'sha256:fourteen', 'options': OPTIONS}
    assert record == {**pin, 'source': 'operator_override', 'material_draft_model': 'qwen3.5:9b'}
    # The same model as the draft, when named explicitly, still needs its own directory.
    with pytest.raises(ValueError, match='its own output directory'):
        review_harness.review_pin('qwen3.5:9b', 'qwen3.5:9b', INSTALLED, tmp_path / 'run-1')


@pytest.mark.parametrize('model, message', [
    ('qwen3:99b', 'not installed locally'),                       # never downloaded
    ('anthropic-api:claude', 'installed local model name'),       # no hosted route
    ('http://127.0.0.1:11434/x', 'installed local model name'),
])
def test_review_override_must_be_an_installed_local_model(tmp_path, model, message):
    with pytest.raises(ValueError, match=message):
        review_harness.review_pin('qwen3.5:9b', model, INSTALLED, tmp_path / 'qwen3-99b-run')
    with pytest.raises(ValueError, match='its own output directory'):
        review_harness.review_pin('qwen3.5:9b', 'qwen3:14b', INSTALLED, tmp_path / 'default-run')


@pytest.fixture
def diagnostic(tmp_path, monkeypatch):
    """A synthetic accepted material diagnostic, and the harness pointed at tmp roots."""
    materials, reviews = tmp_path / 'materials', tmp_path / 'reviews'
    material = materials / 'synthetic-material'
    material.mkdir(parents=True)
    pair_reports = {}
    for stem in ('intro', 'pitch', 'memo'):
        editable = 'docx' if stem == 'memo' else 'pptx'
        pair_reports[stem] = {}
        for extension, key in ((editable, 'editable_sha256'), ('pdf', 'pdf_sha256')):
            data = f'synthetic {stem} {extension}'.encode()
            (material / f'{stem}.{extension}').write_bytes(data)
            pair_reports[stem][key] = hashlib.sha256(data).hexdigest()
    (material / 'result.json').write_text(json.dumps({
        'state': 'accepted', 'acceptance_scope': 'public_synthetic_diagnostic_only',
        'investor_material_accepted': False, 'pair_reports': pair_reports}))
    request = {'input_revision': 'synthetic', 'source_hash': 'source', 'memo_digest': 'memo',
               'sections': SECTIONS}
    (material / 'material_request.json').write_text(json.dumps({**request,
                                                                'digest': digest(request)}))
    (material / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    monkeypatch.setattr(review_harness, 'FRESH_REVIEW_CONTRACT', IMPLEMENTED)
    monkeypatch.setattr(review_harness, 'MATERIAL_ROOT', materials)
    monkeypatch.setattr(review_harness, 'OUTPUT_ROOT', reviews)
    monkeypatch.setattr(review_harness, '_slides', lambda path: DECKS[
        'intro_deck' if path.name == 'intro.pptx' else 'pitch_deck'])
    installed = dict(INSTALLED)
    monkeypatch.setattr(review_harness, 'installed_models', lambda: dict(installed))
    box = {'answers': [PASS], 'models': []}

    def local_model(name, **options):
        assert options == OPTIONS
        model = Reviewer(box['answers'], name)
        box['models'].append(model)
        return model

    monkeypatch.setattr(review_harness, 'LocalModel', local_model)
    return material, reviews, box, installed


def tree(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in sorted(directory.rglob('*')) if path.is_file()}


def test_override_review_is_frozen_in_its_own_directory_and_old_runs_are_untouched(diagnostic):
    material, reviews, box, installed = diagnostic
    default = review_harness.evaluate(material, reviews / 'run-default', operator_attested=True)
    assert default['state'] == 'accepted' and default['review_contract'] == IMPLEMENTED
    assert default['review_model']['source'] == 'material_profile_draft'
    old = tree(reviews / 'run-default')
    material_before = tree(material)

    box['answers'] = [BLOCK]
    override = review_harness.evaluate(material, reviews / 'run-qwen3-14b', operator_attested=True,
                                       review_model='qwen3:14b')
    assert override['state'] == 'blocked' and override['reason'] == 'model_review_blocked'
    assert override['review_model'] == {
        'name': 'qwen3:14b', 'digest': 'sha256:fourteen', 'options': OPTIONS,
        'source': 'operator_override', 'material_draft_model': 'qwen3.5:9b'}
    assert override['acceptance_scope'] == 'public_synthetic_diagnostic_only'
    assert override['investor_material_accepted'] is False
    run = reviews / 'run-qwen3-14b'
    request = json.loads((run / 'material_review_request.json').read_text())
    assert request['review_contract'] == IMPLEMENTED
    assert request['review_model'] == {'name': 'qwen3:14b', 'digest': 'sha256:fourteen',
                                       'options': OPTIONS}
    assert json.loads((run / 'review_model.json').read_text()) == override['review_model']
    rows = json.loads((run / 'material_review_attempts.json').read_text())
    assert [row['model'] for row in rows] == ['qwen3:14b'] and rows[0]['raw_response']
    assert box['models'][-1].name == 'qwen3:14b' and box['models'][-1].calls == 1
    # Neither the earlier diagnostic nor the frozen material input changed by a byte.
    assert tree(reviews / 'run-default') == old and tree(material) == material_before
    # The saved override run replays exactly under its own pinned model, without inference.
    idle = Reviewer([], 'qwen3:14b')
    replayed = review_materials(run, idle)
    assert replayed['review'] == override['review'] and idle.calls == 0
    # The pin is part of the request digest: it cannot be swapped after the fact.
    swapped = {**request, 'review_model': {**request['review_model'], 'name': 'qwen3.5:9b'}}
    (run / 'material_review_request.json').write_text(json.dumps(swapped))
    with pytest.raises(ValueError, match='request digest changed'):
        review_materials(run, Reviewer([], 'qwen3.5:9b'))


def test_override_cannot_reuse_a_directory_or_an_uninstalled_or_changed_model(diagnostic):
    material, reviews, box, installed = diagnostic
    review_harness.evaluate(material, reviews / 'run-qwen3-14b', operator_attested=True,
                            review_model='qwen3:14b')
    saved = tree(reviews / 'run-qwen3-14b')
    with pytest.raises(FileExistsError):
        review_harness.evaluate(material, reviews / 'run-qwen3-14b', operator_attested=True,
                                review_model='qwen3:14b')
    with pytest.raises(ValueError, match='its own output directory'):
        review_harness.evaluate(material, reviews / 'another-run', operator_attested=True,
                                review_model='qwen3:14b')
    with pytest.raises(ValueError, match='not installed locally'):
        review_harness.evaluate(material, reviews / 'run-phi4-mini', operator_attested=True,
                                review_model='phi4-mini')
    assert tree(reviews / 'run-qwen3-14b') == saved
    assert not (reviews / 'another-run').exists() and not (reviews / 'run-phi4-mini').exists()
    with pytest.raises(ValueError, match='operator attestation'):
        review_harness.evaluate(material, reviews / 'x-qwen3-14b', review_model='qwen3:14b')


def test_review_harness_keeps_the_two_call_limit_and_blocks_on_a_changed_digest(diagnostic,
                                                                                 monkeypatch):
    material, reviews, box, installed = diagnostic
    unbindable = {**BLOCK, 'findings': [{**BLOCK['findings'][0],
                                         'unsupported_proposition': 'words not in the sentence'}]}
    box['answers'] = [unbindable, unbindable, PASS]
    result = review_harness.evaluate(material, reviews / 'two-qwen3-14b', operator_attested=True,
                                     review_model='qwen3:14b')
    assert result['state'] == 'blocked' and result['passes'] <= 2
    rows = json.loads((reviews / 'two-qwen3-14b' / 'material_review_attempts.json').read_text())
    assert len(rows) <= 2 and sum(model.calls for model in box['models']) == len(rows)
    assert box['answers'][-1] == PASS            # the third answer was never requested

    # A digest that changes after pinning stops the run before any call.
    calls = {'count': 0}

    def changing():
        calls['count'] += 1
        return {**INSTALLED, 'qwen3:14b': 'sha256:fourteen' if calls['count'] == 1 else 'sha256:new'}

    monkeypatch.setattr(review_harness, 'installed_models', changing)
    box['answers'], box['models'] = [PASS], []
    result = review_harness.evaluate(material, reviews / 'changed-qwen3-14b',
                                     operator_attested=True, review_model='qwen3:14b')
    assert result['state'] == 'blocked'
    assert result['reason'] == 'installed_review_model_digest_changed' and box['models'] == []


def test_review_harness_refuses_an_unimplemented_fresh_contract_before_writing(diagnostic,
                                                                              monkeypatch):
    material, reviews, box, installed = diagnostic
    monkeypatch.setattr(review_harness, 'FRESH_REVIEW_CONTRACT', 'semantic_v99')
    with pytest.raises(ValueError, match='does not implement semantic_v99'):
        review_harness.evaluate(material, reviews / 'run-default', operator_attested=True)
    assert not (reviews / 'run-default').exists() and box['models'] == []
