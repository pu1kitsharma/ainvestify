"""The synthetic reviewer pair diagnostic: clean registry report versus a planted
false receipt assertion. Scripted doubles only; no local model is called."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_review import (REVIEW_INSTRUCTION_V10, compact_review_payload,
                                             review_instruction)
from scripts import evaluate_local_material_review_pair as pair
from scripts.private_material_review_worker import review_materials

FIXTURE = pair.FIXTURE_ROOT / 'false_receipt_pair.synthetic.json'
OPTIONS = {'thinking': False, 'max_tokens': 1200, 'context_tokens': 16384, 'temperature': 0}
INSTALLED = {'qwen3.5:9b': 'sha256:nine', 'qwen3:14b': 'sha256:fourteen'}
# Scripted answers are in the fresh contract's shape.
IMPLEMENTED = 'semantic_v10'
PLANTED = 'The company received the seed funds in full [S1].'
PASS = {'verdict': 'pass', 'findings': [],
        'rationale': 'The supplied deck claims align with the cited memo evidence.'}


def block(choice, proposition, issue='unsupported_claim', *more):
    return {'verdict': 'block',
            'rationale': 'A funding sentence states more than its cited registry entry reports.',
            'findings': [{'sentence_choice': choice, 'issue': issue,
                          'unsupported_proposition': proposition,
                          'explanation': 'The registry entry does not state that any funds '
                                         'were received by the company.'}, *more]}


REPORT = 'A registry lists a seed round with unknown status'
REPORT_FINDING = {'sentence_choice': 'pitch_deck.slide_1.sentence_1', 'issue': 'unsupported_claim',
                  'unsupported_proposition': REPORT,
                  'explanation': 'The reviewer objects to the attributed registry report itself.'}


class Reviewer:
    """Answers from the payload alone. `policy` maps (has planted sentence) to an answer."""

    def __init__(self, policy, name):
        self.policy, self.name, self.calls = policy, name, 0
        self.last_response_text, self.last_route = '', {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        self.calls += 1
        payload = json.loads(evidence)
        planted = any(choice['sentence'] == PLANTED for choice in payload['sentence_choices'])
        self.last_route = {'model': self.name, **OPTIONS}
        self.last_response_text = json.dumps(self.policy(planted, payload))
        return schema.model_validate_json(self.last_response_text)


def discerning(planted, payload):
    """Accepts the control; blocks the defect on the planted sentence and its source."""
    if not planted:
        return PASS
    choice = next(item for item in payload['sentence_choices'] if item['sentence'] == PLANTED)
    return block(choice['id'], 'received the seed funds in full')


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(pair, 'OUTPUT_ROOT', tmp_path)
    installed = dict(INSTALLED)
    monkeypatch.setattr(pair, 'installed_models', lambda: dict(installed))
    box = {'policy': discerning, 'models': []}

    def local_model(name, **options):
        assert options == OPTIONS
        model = Reviewer(box['policy'], name)
        box['models'].append(model)
        return model

    monkeypatch.setattr(pair, 'LocalModel', local_model)

    def run(name='pair-qwen3-5-9b', model='qwen3.5:9b', **kwargs):
        kwargs.setdefault('review_contract', IMPLEMENTED)
        kwargs.setdefault('operator_attested', True)
        return pair.evaluate(FIXTURE, tmp_path / name, model, **kwargs)

    return tmp_path, box, installed, run


def test_fixture_is_a_synthetic_pair_differing_only_by_the_planted_sentence():
    fixture = pair.load_fixture(FIXTURE)
    control, defect = fixture['decks']['control'], fixture['decks']['defect']
    assert control['intro_deck'] == defect['intro_deck']
    control_body, defect_body = control['pitch_deck'][0][1], defect['pitch_deck'][0][1]
    # The clean deck: a source-qualified registry report with unknown status and no receipt claim.
    assert control_body == 'A registry lists a seed round with unknown status [S1].'
    assert 'received' not in control_body
    # The defect: exactly that report plus one receipt assertion citing the same source.
    assert defect_body == control_body + ' ' + PLANTED
    assert fixture['planted']['sentence'] == PLANTED and PLANTED in defect_body
    assert fixture['planted']['source_id'] == '[S1]'
    assert 'example.invalid' in json.dumps(fixture['memo_sections'])
    with pytest.raises(ValueError, match='review fixture folder'):
        pair.load_fixture(pair.FIXTURE_ROOT.parent / 'public_memo' / 'sparse_conflict.synthetic.json')


@pytest.mark.parametrize('change, message', [
    (lambda data: data['control']['pitch_deck'][0].__setitem__(1, data['defect']['pitch_deck'][0][1]),
     'not in the control'),
    (lambda data: data['defect']['planted'].__setitem__('sentence', 'A sentence nowhere in the deck.'),
     'must be in the defect deck'),
    (lambda data: data['defect']['planted'].__setitem__('source_id', '[S9]'),
     'must cite a source the memo also cites'),
    (lambda data: data['memo_sections'][0].__setitem__(2, '[S1] https://example.com/real'),
     'only example.invalid'),
    (lambda data: data.__setitem__('classification', 'public'), 'classification synthetic'),
    (lambda data: data['defect']['pitch_deck'][0].__setitem__(
        1, 'A different opening sentence [S1]. ' + PLANTED), 'differ only by the planted sentence'),
    # Any second difference is refused: a changed heading, another slide, an extra sentence.
    (lambda data: data['defect']['pitch_deck'][0].__setitem__(0, 'Funding secured'),
     'differ only by the planted sentence'),
    (lambda data: data['defect']['pitch_deck'][0].__setitem__(
        1, data['defect']['pitch_deck'][0][1] + ' The round was led by a major fund [S1].'),
     'differ only by the planted sentence'),
    (lambda data: data['defect'].__setitem__('intro_deck', [[
        'Company overview', 'Example Labs is the market leader [S2].', '[S2] x', 'statement']]),
     'differ only by the planted sentence'),
    (lambda data: data['defect']['pitch_deck'][0].__setitem__(
        1, data['defect']['pitch_deck'][0][1] + ' ' + PLANTED), 'in the defect deck once'),
])
def test_fixture_loader_rejects_a_pair_that_is_not_a_clean_minimal_contrast(tmp_path, monkeypatch,
                                                                         change, message):
    data = json.loads(FIXTURE.read_text())
    change(data)
    monkeypatch.setattr(pair, 'FIXTURE_ROOT', tmp_path)
    path = tmp_path / 'broken.synthetic.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        pair.load_fixture(path)


@pytest.mark.parametrize('case', ['control', 'defect'])
def test_request_payload_offers_complete_memo_evidence_for_every_cited_source(case):
    """Before any live run: every source a deck cites has its memo spans offered, whole."""
    fixture = pair.load_fixture(FIXTURE)
    base = {'review_contract': pair.FRESH_REVIEW_CONTRACT, 'input_revision': 'synthetic',
            'source_hash': fixture['sha256'], 'memo_digest': digest(fixture['memo_sections']),
            'material_digest': digest(fixture['decks'][case]),
            'memo_sections': fixture['memo_sections'], 'decks': fixture['decks'][case],
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'sha256:nine', 'options': OPTIONS}}
    payload = compact_review_payload({**base, 'digest': digest(base)})
    spans = [item['exact_span'] for item in payload['memo_evidence']]
    memo_text = {index: section[1] for index, section in enumerate(fixture['memo_sections'])}
    # Each offered span is a complete memo sentence, copied exactly, ending in its period.
    for item in payload['memo_evidence']:
        assert item['exact_span'] in memo_text[item['section_index']]
        assert item['exact_span'].endswith('.') and '[S' in item['exact_span']
    assert payload['evidence_scope']['supplied_source_ids'] == ['[S1]', '[S2]']
    assert payload['evidence_scope']['supplied_memo_span_count'] == len(spans) == 4
    # Every memo sentence carrying a cited source is offered: nothing is truncated or dropped.
    for source in ('[S1]', '[S2]'):
        in_memo = [sentence.strip() + '.' for section in fixture['memo_sections']
                   for sentence in section[1].split('.') if source in sentence]
        assert sorted(span for span in spans if source in span) == sorted(in_memo)
        assert len(in_memo) == 2
    # Every selectable sentence is offered all spans of the source it cites, and only those.
    choices = payload['sentence_choices']
    assert len(choices) == (4 if case == 'defect' else 3)
    for choice in choices:
        source = '[S1]' if '[S1]' in choice['sentence'] else '[S2]'
        offered = [spans[index] for index in choice['memo_evidence_indices']]
        assert offered == [span for span in spans if source in span] and len(offered) == 2
    planted = [choice for choice in choices if choice['sentence'] == PLANTED]
    assert len(planted) == (1 if case == 'defect' else 0)
    if planted:
        assert any('does not state that any funds were received' in spans[index]
                   for index in planted[0]['memo_evidence_indices'])


def finding(**changes):
    return {'deck': 'pitch_deck', 'slide_index': 0, 'issue': 'unsupported_claim',
            'body_quote': PLANTED, 'memo_quote': 'does not state that any funds were received [S1].',
            **changes}


def blocked(*findings):
    return {'state': 'blocked', 'reason': 'model_review_blocked', 'review': {'findings': list(findings)}}


def test_scoring_is_exact_about_the_planted_sentence_and_its_source():
    planted = pair.load_fixture(FIXTURE)['planted']
    exact = pair.score_case('defect', blocked(finding()), planted)
    assert exact['passed'] and exact['planted_sentence_flagged_exactly'] and exact['findings_elsewhere'] == 0
    assert pair.score_case('defect', blocked(finding(issue='contradiction')), planted)['passed']
    for wrong in (finding(body_quote='A registry lists a seed round with unknown status [S1].'),
                  finding(deck='intro_deck'), finding(slide_index=1),
                  finding(memo_quote='The company page reports no revenue or customer figures [S2].'),
                  finding(memo_quote=None), finding(issue='heading_body_mismatch'),
                  finding(unsupported_proposition='a proposition from another sentence')):
        scored = pair.score_case('defect', blocked(wrong), planted)
        assert not scored['passed'] and scored['findings_elsewhere'] == 1
    assert pair.score_case('defect', blocked(finding(
        unsupported_proposition='received the seed funds in full')), planted)['passed']
    # The planted finding plus any other finding is not a pass: the extra one is a
    # false positive on text the control also contains.
    extra = finding(body_quote='A registry lists a seed round with unknown status [S1].')
    both = pair.score_case('defect', blocked(finding(), extra), planted)
    assert both['planted_sentence_flagged_exactly'] and both['findings_elsewhere'] == 1
    assert not both['passed']
    # A pass, an unfinished review or an exhausted retry is a miss, not a detection.
    for result in ({'state': 'accepted', 'review': {'findings': []}},
                   {'state': 'needs_resume', 'reason': 'material_review_pass_budget_exhausted'},
                   {'state': 'blocked', 'reason': 'bounded_material_review_validation_exhausted'},
                   {'state': 'blocked', 'reason': 'material_review_block_withdrawn_unbound',
                    'review': {'findings': []}}):
        assert not pair.score_case('defect', result, planted)['passed']
    # The control passes only as an accepted review with no finding.
    assert pair.score_case('control', {'state': 'accepted', 'review': {'findings': []}}, planted)['passed']
    assert not pair.score_case('control', blocked(finding()), planted)['passed']
    assert pair.score_case('control', blocked(finding()), planted)['false_positive_findings'] == 1
    assert not pair.score_case('control', {'state': 'needs_resume'}, planted)['passed']


def rows_instruction(directory):
    return [row['instruction'] for row in
            json.loads((directory / 'material_review_attempts.json').read_text())]


def test_discerning_reviewer_passes_the_pair_in_two_frozen_directories(harness):
    root, box, installed, run = harness
    card = run()
    assert card['pair_passed'] and not card['control_false_positive']
    assert not card['defect_missed_or_misplaced']
    assert [(case['case'], case['passed'], case['passes']) for case in card['cases']] == [
        ('control', True, 1), ('defect', True, 1)]
    assert card['review_model'] == {'name': 'qwen3.5:9b', 'digest': 'sha256:nine',
                                    'options': OPTIONS, 'source': 'operator_override',
                                    'material_draft_model': 'qwen3.5:9b'}
    # A diagnostic: nothing is accepted for investors and human review is pending.
    assert card['acceptance_scope'] == 'public_synthetic_diagnostic_only'
    assert card['investor_material_accepted'] is False and card['independent_review'] == 'pending'
    run_dir = root / 'pair-qwen3-5-9b'
    assert json.loads((run_dir / 'scorecard.json').read_text()) == card
    profile = json.loads((run_dir / 'profile.json').read_text())
    assert (profile['max_passes_per_case'], profile['calls_per_pass'], profile['seconds_per_pass']) == (2, 1, 105)
    requests = {}
    for case in ('control', 'defect'):
        directory = run_dir / case
        request = json.loads((directory / 'material_review_request.json').read_text())
        requests[case] = request
        assert request['review_contract'] == pair.FRESH_REVIEW_CONTRACT == 'semantic_v10'
        assert rows_instruction(directory) == [REVIEW_INSTRUCTION_V10]
        assert request['review_model'] == {'name': 'qwen3.5:9b', 'digest': 'sha256:nine',
                                           'options': OPTIONS}
        assert json.loads((directory / 'material_review_budget.json').read_text()) == {'seconds': 105}
        rows = json.loads((directory / 'material_review_attempts.json').read_text())
        assert len(rows) == 1 and rows[0]['raw_response'] and rows[0]['model'] == 'qwen3.5:9b'
        # Each frozen case replays exactly, without inference.
        saved = json.loads((directory / 'material_review_result.json').read_text())
        assert review_materials(directory, pair.NoInference('qwen3.5:9b')) == saved
    assert requests['control']['digest'] != requests['defect']['digest']
    assert requests['control']['memo_sections'] == requests['defect']['memo_sections']
    defect = json.loads((run_dir / 'defect' / 'material_review_result.json').read_text())
    assert defect['review']['findings'][0]['body_quote'] == PLANTED
    assert defect['review']['findings'][0]['unsupported_proposition'] == 'received the seed funds in full'
    assert sum(model.calls for model in box['models']) == 2


@pytest.mark.parametrize('policy, control_ok, defect_ok', [
    (lambda planted, payload: PASS, True, False),                                  # passes everything
    (lambda planted, payload: block('pitch_deck.slide_1.sentence_1', REPORT), False, False),  # blocks the report
    (lambda planted, payload: PASS if not planted else block('pitch_deck.slide_1.sentence_1', REPORT),
     True, False),                                                                 # blocks the wrong sentence
    # Finds the planted sentence but also objects to the clean report beside it.
    (lambda planted, payload: PASS if not planted else block(
        'pitch_deck.slide_1.sentence_2', 'received the seed funds in full', 'unsupported_claim',
        REPORT_FINDING), True, False),
])
def test_reviewer_that_passes_or_blocks_indiscriminately_fails_the_pair(harness, policy, control_ok,
                                                                        defect_ok):
    root, box, installed, run = harness
    box['policy'] = policy
    card = run()
    assert not card['pair_passed']
    assert [case['passed'] for case in card['cases']] == [control_ok, defect_ok]
    assert card['control_false_positive'] is (not control_ok)
    assert card['defect_missed_or_misplaced'] is (not defect_ok)


def test_two_call_cap_per_case_and_no_third_call(harness):
    root, box, installed, run = harness
    # An unbindable finding: the quoted proposition is not in the chosen sentence.
    box['policy'] = lambda planted, payload: block('pitch_deck.slide_1.sentence_1',
                                                   'words that are not in the sentence')
    card = run()
    assert not card['pair_passed']
    for case in ('control', 'defect'):
        rows = json.loads((root / 'pair-qwen3-5-9b' / case / 'material_review_attempts.json').read_text())
        assert len(rows) <= 2
    assert all(case['passes'] <= 2 for case in card['cases'])
    assert sum(model.calls for model in box['models']) <= 4


def test_runs_are_pinned_distinct_and_never_reuse_or_touch_an_earlier_directory(harness):
    root, box, installed, run = harness
    first = run()
    saved = {str(path.relative_to(root)): path.read_bytes()
             for path in sorted((root / 'pair-qwen3-5-9b').rglob('*')) if path.is_file()}
    with pytest.raises(FileExistsError):
        run()
    other = run(name='pair-qwen3-14b', model='qwen3:14b')
    assert other['review_model']['digest'] == 'sha256:fourteen' and other['pair_passed']
    assert {str(path.relative_to(root)): path.read_bytes()
            for path in sorted((root / 'pair-qwen3-5-9b').rglob('*')) if path.is_file()} == saved
    for name, model, message in (('unnamed-run', 'qwen3:14b', 'its own output directory'),
                                 ('pair-phi4-mini', 'phi4-mini', 'not installed locally'),
                                 ('pair-anthropic', 'anthropic-api:claude', 'installed local model name')):
        with pytest.raises(ValueError, match=message):
            run(name=name, model=model)
        assert not (root / name).exists()
    with pytest.raises(ValueError, match='operator attestation'):
        run(name='x-qwen3-14b', model='qwen3:14b', operator_attested=False)
    with pytest.raises(ValueError, match='ignored output root'):
        pair.evaluate(FIXTURE, root.parent / 'elsewhere-qwen3-14b', 'qwen3:14b',
                      operator_attested=True, review_contract=IMPLEMENTED)
    assert first['pair_passed']


def test_changed_model_digest_blocks_before_any_call(harness, monkeypatch):
    root, box, installed, run = harness
    calls = {'count': 0}

    def changing():
        calls['count'] += 1
        return {**INSTALLED, 'qwen3.5:9b': 'sha256:nine' if calls['count'] == 1 else 'sha256:new'}

    monkeypatch.setattr(pair, 'installed_models', changing)
    card = run()
    assert not card['pair_passed'] and box['models'] == []
    assert {case['reason'] for case in card['cases']} == {'installed_review_model_digest_changed'}


def test_default_contract_is_v10_and_an_unimplemented_one_is_refused_before_writing(harness):
    root, box, installed, run = harness
    assert pair.FRESH_REVIEW_CONTRACT == 'semantic_v10'
    assert review_instruction({'review_contract': 'semantic_v10'}) == REVIEW_INSTRUCTION_V10
    # The default run needs no contract argument.
    card = pair.evaluate(FIXTURE, root / 'default-qwen3-5-9b', 'qwen3.5:9b', operator_attested=True)
    assert card['review_contract'] == 'semantic_v10' and card['pair_passed']
    with pytest.raises(ValueError, match='does not implement semantic_v99'):
        run(name='v99-qwen3-5-9b', review_contract='semantic_v99')
    assert not (root / 'v99-qwen3-5-9b').exists()
