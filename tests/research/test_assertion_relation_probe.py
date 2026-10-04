"""The assertion-level relation probe under its first recorded contract (v2, capital
receipt). Scripted doubles only; no local model is called. The generic v3 contract and
the holdout pair are in test_assertion_relation_holdout.py."""
import json
import hashlib

import pytest

from agents.preparation.preparation_budget import PreparationBudgetExceeded
from scripts import evaluate_local_assertion_relation_probe as probe
from scripts.evaluate_local_material_review_pair import FIXTURE_ROOT

FIXTURE = FIXTURE_ROOT / 'false_receipt_pair.synthetic.json'
HOLDOUT = FIXTURE_ROOT / 'invented_contract_holdout.synthetic.json'
INSTALLED = {'qwen3.5:9b': 'sha256:nine', 'qwen3:14b': 'sha256:fourteen', 'phi4-mini': 'sha256:phi'}
PLANTED = 'The company received the seed funds in full [S1].'
REGISTRY = 'A registry lists a seed round with unknown status [S1].'
IDS = ['intro_deck.slide_1.sentence_1', 'intro_deck.slide_1.sentence_2',
       'pitch_deck.slide_1.sentence_1', 'pitch_deck.slide_1.sentence_2']


def judgment(classification='supported_as_source_report', receipt=False, clause=None):
    return {'classification': classification, 'asserts_capital_receipt': receipt,
            'challenged_clause': clause,
            'reason': 'Compared the sentence with the supplied source spans.'}


def capable(payload):
    """Classifies from the sentence and spans alone, as the model must."""
    if 'received the seed funds' in payload['sentence']:
        return judgment('unsupported_assertion', True, 'received the seed funds in full')
    return judgment()


class Double:
    def __init__(self, policy, name, options):
        self.policy, self.name, self.options, self.calls, self.seen = policy, name, options, 0, []
        self.last_response_text, self.last_call = '', {'model': name, **options}

    def generate(self, instruction, evidence, schema):
        self.calls += 1
        self.seen.append((instruction, json.loads(evidence)))
        value = self.policy(json.loads(evidence))
        if isinstance(value, Exception):
            raise value
        self.last_response_text = json.dumps(value)
        return schema.model_validate_json(self.last_response_text)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(probe, 'installed_models', lambda: dict(INSTALLED))
    box = {'policy': capable, 'models': []}

    def local_model(name, **options):
        # The real adapter refuses thinking for a model that has no thinking mode.
        if options['thinking'] and not name.startswith(('qwen3:', 'qwen3.5:')):
            raise ValueError('Reasoning requires a supported installed thinking model')
        model = Double(box['policy'], name, options)
        box['models'].append(model)
        return model

    monkeypatch.setattr(probe, 'LocalModel', local_model)

    def run(name='probe-qwen3-5-9b', model='qwen3.5:9b', **kwargs):
        kwargs.setdefault('operator_attested', True)
        kwargs.setdefault('contract', probe.LEGACY_CONTRACT)
        return probe.evaluate(FIXTURE, tmp_path / name, model, **kwargs)

    return tmp_path, box, run


def test_one_row_per_fixed_sentence_id_with_complete_exact_spans():
    from scripts.evaluate_local_material_review_pair import load_fixture
    fixture = load_fixture(FIXTURE)
    rows = probe.probe_rows(fixture, probe.LEGACY_CONTRACT)
    assert [row['sentence_id'] for row in rows] == IDS
    assert [row['role'] for row in rows] == ['clean_company_page', 'clean_company_page',
                                             'clean_registry_report', 'planted_false_receipt']
    # A sentence present in both decks is one row; only the planted one is defect-only.
    assert [row['cases'] for row in rows] == [['control', 'defect']] * 3 + [['defect']]
    assert rows[2]['sentence'] == REGISTRY and rows[3]['sentence'] == PLANTED
    memo = ' '.join(section[1] for section in fixture['memo_sections'])
    for row in rows:
        source = '[S1]' if '[S1]' in row['sentence'] else '[S2]'
        assert [item['source_id'] for item in row['source_spans']] == [source, source]
        assert all(item['exact_span'] in memo and item['exact_span'].endswith('.')
                   for item in row['source_spans'])
        # The model sees the sentence and spans only: no ID, role, case or expectation.
        payload = probe.probe_payload(row, probe.LEGACY_CONTRACT)
        assert set(payload) == {'probe_contract', 'sentence', 'source_spans'}
        assert 'planted' not in json.dumps(payload) and 'control' not in json.dumps(payload)
    assert any('does not state that any funds were received' in item['exact_span']
               for item in rows[3]['source_spans'])
    # The planted and the registry rows are given the identical spans of the same source.
    assert rows[2]['source_spans'] == rows[3]['source_spans']


def test_instruction_is_a_neutral_classification_not_a_defect_hunt():
    text = probe.INSTRUCTION.casefold()
    for word in ('defect', 'problem', 'block', 'find', 'review', 'receipt of funds', 'registry'):
        assert word not in text
    assert all(label in probe.INSTRUCTION for label in (
        'supported_as_source_report', 'unsupported_assertion', 'insufficient_evidence',
        'asserts_capital_receipt', 'challenged_clause'))
    schema = probe.SentenceJudgment.model_json_schema()
    assert set(schema['required']) == {'classification', 'asserts_capital_receipt',
                                       'challenged_clause', 'reason'}


def test_capable_model_is_go_with_one_call_per_sentence_and_shared_unchanged_rows(harness):
    root, box, run = harness
    card = run()
    assert card['probe_contract'] == 'assertion-relation-probe-v2' and 'flagged_claim' not in card
    assert card['decision'] == 'go' and card['decision_note'] is None
    assert card['model_calls'] == 4 == box['models'][0].calls
    assert [(row['sentence_id'], row['classification'], row['asserts_capital_receipt'],
             row['challenged_clause'], row['passed']) for row in card['rows']] == [
        (IDS[0], 'supported_as_source_report', False, None, True),
        (IDS[1], 'supported_as_source_report', False, None, True),
        (IDS[2], 'supported_as_source_report', False, None, True),
        (IDS[3], 'unsupported_assertion', True, 'received the seed funds in full', True)]
    # Unchanged rows keep their control classification in the defect case by sharing
    # the one recorded judgment; the defect case adds only the planted row.
    assert card['cases'] == {'control': IDS[:3], 'defect': IDS}
    assert card['unchanged_rows_share_one_recorded_judgment'] is True
    assert len({row['response_id'] for row in card['rows']}) == 4
    assert card['planted_row_unsupported_with_receipt'] and card['clean_rows_not_supported'] == 0
    # A probe result: nothing in production changed and nothing is accepted.
    assert card['acceptance_scope'] == 'public_synthetic_probe_only'
    assert card['production_review_contract'] == 'unchanged'
    assert card['investor_material_accepted'] is False and card['independent_review'] == 'pending'
    assert all(instruction == probe.INSTRUCTION for instruction, _ in box['models'][0].seen)
    assert card['review_model'] == {'name': 'qwen3.5:9b', 'digest': 'sha256:nine',
                                    'options': probe.OPTIONS[False], 'source': 'operator_override',
                                    'material_draft_model': 'qwen3.5:9b'}


def on(sentence_part, answer):
    return lambda payload: answer if sentence_part in payload['sentence'] else capable(payload)


@pytest.mark.parametrize('policy, failed_id, outcome', [
    # Safe in release, but not the capability this benchmark tests.
    (on('registry lists', judgment('insufficient_evidence')), IDS[2], 'answered'),
    (on('scheduling software', judgment('insufficient_evidence')), IDS[0], 'answered'),
    # Over-flagging a clean attributed report or clean company-page text.
    (on('registry lists', judgment('unsupported_assertion', False, 'unknown status')), IDS[2],
     'answered'),
    (on('no revenue', judgment('unsupported_assertion', False, 'no revenue')), IDS[1], 'answered'),
    # The clean registry report read as a receipt claim.
    (on('registry lists', judgment(receipt=True)), IDS[2], 'answered'),
    # The planted receipt assertion missed, or caught without recognising the receipt.
    (on('received the seed funds', judgment()), IDS[3], 'answered'),
    (on('received the seed funds', judgment('insufficient_evidence', True)), IDS[3], 'answered'),
    (on('received the seed funds',
        judgment('unsupported_assertion', False, 'received the seed funds')), IDS[3], 'answered'),
    # A challenged clause that is not the sentence's own words, or one given for support.
    (on('received the seed funds',
        judgment('unsupported_assertion', True, 'the money arrived in the bank')), IDS[3],
     'unbound_challenged_clause'),
    (on('registry lists', judgment(clause='unknown status')), IDS[2], 'unbound_challenged_clause'),
])
def test_any_single_wrong_row_is_no_go_and_a_model_limitation(harness, policy, failed_id, outcome):
    root, box, run = harness
    box['policy'] = policy
    card = run()
    assert card['decision'] == 'no_go_model_limitation'
    assert 'do not cycle the prompt' in card['decision_note']
    failed = [row for row in card['rows'] if not row['passed']]
    assert [(row['sentence_id'], row['outcome']) for row in failed] == [(failed_id, outcome)]
    assert card['model_calls'] == 4


def test_indiscriminate_models_are_no_go_either_way(harness):
    root, box, run = harness
    box['policy'] = lambda payload: judgment()
    lenient = run(name='lenient-qwen3-5-9b')
    assert lenient['decision'] == 'no_go_model_limitation'
    assert not lenient['planted_row_unsupported_with_receipt']
    box['policy'] = lambda payload: judgment('unsupported_assertion', True,
                                             payload['sentence'][:12])
    strict = run(name='strict-qwen3-5-9b')
    assert strict['decision'] == 'no_go_model_limitation'
    assert strict['clean_rows_not_supported'] == 3 and strict['clean_rows_asserting_capital_receipt'] == 3
    box['policy'] = lambda payload: judgment('insufficient_evidence')
    unsure = run(name='unsure-qwen3-5-9b')
    assert unsure['decision'] == 'no_go_model_limitation'
    assert unsure['clean_rows_insufficient_evidence'] == 3


def test_invalid_or_missing_answers_are_recorded_and_never_retried(harness):
    root, box, run = harness
    box['policy'] = on('registry lists', {'classification': 'supported', 'reason': 'x'})
    card = run(name='invalid-qwen3-5-9b')
    assert card['decision'] == 'no_go_model_limitation' and card['answers_invalid_or_unbound'] == 1
    assert card['model_calls'] == 4 and box['models'][-1].calls == 4       # no second call
    rows = json.loads((root / 'invalid-qwen3-5-9b' / 'attempts.json').read_text())
    bad = next(row for row in rows if row.get('error'))
    assert bad['raw_response'] and bad['failure_kind'] == 'schema_validation'

    cancelled = PreparationBudgetExceeded('Preparation reached its time limit during inference.')
    box['policy'] = on('received the seed funds', cancelled)
    card = run(name='cancelled-qwen3-5-9b')
    assert card['rows_without_answer'] == 1 and card['decision'] == 'no_go_model_limitation'
    assert box['models'][-1].calls == 4
    assert next(row for row in card['rows'] if row['sentence_id'] == IDS[3])['outcome'] == 'no_answer'


def test_raw_record_is_immutable_and_replays_exactly(harness):
    root, box, run = harness
    card = run()
    directory = root / 'probe-qwen3-5-9b'
    assert sorted(path.name for path in directory.iterdir()) == [
        'attempts.json', 'profile.json', 'scorecard.json']
    for name in ('attempts.json', 'profile.json'):
        assert (directory / name).stat().st_mode & 0o777 == 0o400
    assert json.loads((directory / 'scorecard.json').read_text()) == card
    saved = (directory / 'attempts.json').read_bytes()
    # Replay rebuilds the same scorecard from the raw attempts, with no model.
    calls = box['models'][0].calls
    assert probe.replay(directory, FIXTURE) == card
    assert box['models'][0].calls == calls and (directory / 'attempts.json').read_bytes() == saved
    profile = json.loads((directory / 'profile.json').read_text())
    assert (profile['calls_per_sentence'], profile['retries'], profile['seconds_per_call']) == (1, 0, 60)
    assert profile['sentence_ids'] == IDS and profile['review_model']['digest'] == 'sha256:nine'
    # An existing run directory is never reused or rewritten.
    with pytest.raises(FileExistsError):
        run()
    assert (directory / 'attempts.json').read_bytes() == saved


@pytest.mark.parametrize('tamper, message', [
    (lambda rows: rows[0].__setitem__('raw_response', rows[0]['raw_response'].replace(
        'supported_as_source_report', 'unsupported_assertion')), 'differs from the frozen probe'),
    (lambda rows: rows[0].__setitem__('answer', {**rows[0]['answer'],
                                                 'asserts_capital_receipt': True}), 'differs'),
    (lambda rows: rows[0]['input'].__setitem__('sentence', 'A different sentence [S2].'),
     'differs from the frozen probe'),
    (lambda rows: rows[0].__setitem__('instruction', 'Find every defect.'),
     'differs from the frozen probe'),
    (lambda rows: rows[0].__setitem__('model', 'qwen3:14b'), 'differs from the frozen probe'),
    (lambda rows: rows.append(dict(rows[0])), 'differs from the frozen probe'),
])
def test_replay_rejects_any_altered_saved_response(harness, tamper, message):
    root, box, run = harness
    run()
    directory = root / 'probe-qwen3-5-9b'
    rows = json.loads((directory / 'attempts.json').read_text())
    tamper(rows)
    (directory / 'attempts.json').chmod(0o600)
    (directory / 'attempts.json').write_text(json.dumps(rows))
    with pytest.raises(ValueError, match=message):
        probe.replay(directory, FIXTURE)


def test_thinking_mode_needs_a_supporting_model_and_its_own_directory(harness):
    root, box, run = harness
    card = run(name='probe-qwen3-5-9b-thinking', thinking=True)
    assert card['thinking'] is True and card['decision'] == 'go'
    assert card['review_model']['options'] == probe.OPTIONS[True]
    assert box['models'][-1].options['thinking'] is True
    profile = json.loads((root / 'probe-qwen3-5-9b-thinking' / 'profile.json').read_text())
    assert profile['thinking'] is True and profile['seconds_per_call'] == 105
    # A plain run and a thinking run cannot use each other's directory names.
    with pytest.raises(ValueError, match='named with "thinking"'):
        run(name='second-qwen3-5-9b', thinking=True)
    with pytest.raises(ValueError, match='named with "thinking"'):
        run(name='second-qwen3-5-9b-thinking', thinking=False)
    # A model without a thinking mode is refused before anything is written.
    with pytest.raises(ValueError, match='supported installed thinking model'):
        run(name='probe-phi4-mini-thinking', model='phi4-mini', thinking=True)
    for name in ('second-qwen3-5-9b', 'second-qwen3-5-9b-thinking', 'probe-phi4-mini-thinking'):
        assert not (root / name).exists()


def test_model_must_be_installed_local_pinned_and_named_in_the_directory(harness, monkeypatch):
    root, box, run = harness
    for name, model, message in (('probe-other', 'qwen3:14b', 'its own output directory'),
                                 ('probe-qwen3-99b', 'qwen3:99b', 'not installed locally'),
                                 ('probe-anthropic', 'anthropic-api:claude',
                                  'installed local model name')):
        with pytest.raises(ValueError, match=message):
            run(name=name, model=model)
        assert not (root / name).exists()
    with pytest.raises(ValueError, match='operator attestation'):
        run(operator_attested=False)
    with pytest.raises(ValueError, match='ignored output root'):
        probe.evaluate(FIXTURE, root.parent / 'elsewhere-qwen3-5-9b', 'qwen3.5:9b',
                       operator_attested=True, contract=probe.LEGACY_CONTRACT)
    other = run(name='probe-qwen3-14b', model='qwen3:14b')
    assert other['review_model']['digest'] == 'sha256:fourteen'

    # A digest that changes after pinning stops the probe before any call.
    calls = {'count': 0}

    def changing():
        calls['count'] += 1
        return {**INSTALLED, 'qwen3.5:9b': 'sha256:nine' if calls['count'] == 1 else 'sha256:new'}

    monkeypatch.setattr(probe, 'installed_models', changing)
    box['models'] = []
    card = run(name='changed-qwen3-5-9b')
    assert card['stopped'] == 'installed_model_digest_changed'
    assert card['decision'] == 'no_go_model_limitation' and card['model_calls'] == 0
    assert box['models'][0].calls == 0 and card['rows_without_answer'] == 4


def relation_judgment(classification='supported_as_source_report', clause=None):
    return {'classification': classification, 'challenged_clause': clause,
            'reason': 'Compared the exact sentence with the cited source spans.'}


def relation_capable(payload):
    sentence = payload['sentence']
    if 'received the seed funds' in sentence:
        return relation_judgment('unsupported_assertion', 'received the seed funds in full')
    if 'signed multi-year supply contracts' in sentence:
        return relation_judgment('unsupported_assertion', 'signed multi-year supply contracts')
    return relation_judgment()


def test_v4_relation_only_contract_omits_flag_from_every_model_surface(harness):
    root, box, run = harness
    box['policy'] = relation_capable
    contract = probe.RELATION_ONLY_CONTRACT
    assert contract == 'assertion-relation-probe-v4'
    assert set(probe.RelationOnlyJudgment.model_json_schema()['required']) == {
        'classification', 'challenged_clause', 'reason'}
    for word in ('flagged_claim', 'asserts_flagged_claim', 'asserts_capital_receipt',
                 'signed_contract'):
        assert word not in probe.INSTRUCTION_V4
        assert word not in json.dumps(probe.RelationOnlyJudgment.model_json_schema())
    for name, fixture in [('relation-funding-qwen3-5-9b', FIXTURE),
                          ('relation-holdout-qwen3-5-9b', HOLDOUT)]:
        card = probe.evaluate(fixture, root / name, 'qwen3.5:9b',
                              operator_attested=True, contract=contract)
        assert card['decision'] == 'go' and card['model_calls'] == 4
        assert card['planted_row_unsupported'] is True
        assert card['clean_rows_not_supported'] == 0
        assert [item['classification'] for item in card['rows']] == [
            'supported_as_source_report'] * 3 + ['unsupported_assertion']
        assert all('asserts_' not in json.dumps(item) for item in card['rows'])
        assert 'flagged_claim' not in card
        directory = root / name
        profile = json.loads((directory / 'profile.json').read_text())
        attempts = json.loads((directory / 'attempts.json').read_text())
        assert 'flagged_claim' not in profile
        assert all(set(item['input']) == {'probe_contract', 'sentence', 'source_spans'}
                   for item in attempts)
        assert all(item['schema'] == probe.RelationOnlyJudgment.model_json_schema()
                   and item['instruction'] == probe.INSTRUCTION_V4 for item in attempts)
        assert probe.replay(directory, fixture) == card


def test_v4_wrong_relation_invalid_clause_and_flagged_shape_fail_without_retry(harness):
    root, box, _ = harness
    contract = probe.RELATION_ONLY_CONTRACT
    cases = [
        ('missed', lambda payload: relation_judgment(), 'answered'),
        ('unbound', lambda payload: relation_judgment(
            'unsupported_assertion', 'money arrived in the bank')
         if 'received the seed funds' in payload['sentence'] else relation_judgment(),
         'unbound_challenged_clause'),
        ('flagged-shape', lambda payload: {**relation_capable(payload),
                                          'asserts_flagged_claim': False}, 'invalid_answer'),
    ]
    for name, policy, outcome in cases:
        box['policy'] = policy
        card = probe.evaluate(FIXTURE, root / f'{name}-qwen3-5-9b', 'qwen3.5:9b',
                              operator_attested=True, contract=contract)
        assert card['decision'] == 'no_go_model_limitation'
        assert card['model_calls'] == 4 == box['models'][-1].calls
        if name == 'flagged-shape':
            assert all(row['outcome'] == outcome for row in card['rows'])
        else:
            assert card['rows'][-1]['outcome'] == outcome
        assert probe.replay(root / f'{name}-qwen3-5-9b', FIXTURE) == card


def batch_capable(payload):
    assert payload['probe_contract'] == probe.BATCH_CONTRACT
    return {row['row_id']: relation_capable(row) for row in payload['rows']}


def scale_capable(payload):
    assert payload['probe_contract'] == probe.SCALE_CONTRACT
    return {row['row_id']: relation_capable(row) for row in payload['rows']}


def test_v5_one_fixed_row_call_per_deck_passes_both_synthetic_pairs(harness):
    root, box, _ = harness
    box['policy'] = batch_capable
    for name, fixture in [('batch-funding-qwen3-5-9b', FIXTURE),
                          ('batch-holdout-qwen3-5-9b', HOLDOUT)]:
        card = probe.evaluate(fixture, root / name, 'qwen3.5:9b',
                              operator_attested=True, contract=probe.BATCH_CONTRACT)
        assert card['decision'] == 'go' and card['model_calls'] == 2
        assert card['calls_per_deck'] == 1 and card['retries'] == 0
        assert card['planted_row_unsupported'] and card['clean_rows_not_supported'] == 0
        assert len(card['rows']) == 4 and len({row['response_id'] for row in card['rows']}) == 2
        assert all('asserts_' not in json.dumps(row) for row in card['rows'])
        directory = root / name
        profile = json.loads((directory / 'profile.json').read_text())
        attempts = json.loads((directory / 'attempts.json').read_text())
        assert profile['review_model']['digest'] == 'sha256:nine'
        assert profile['seconds_per_call'] == 105
        assert profile['deck_schema_sha256'] == {
            deck: probe.digest(attempt['schema'])
            for deck, attempt in zip(('intro_deck', 'pitch_deck'), attempts)}
        assert [attempt['input']['deck'] for attempt in attempts] == ['intro_deck', 'pitch_deck']
        assert all(attempt['task'] == probe.BATCH_TASK and
                   attempt['instruction'] == probe.INSTRUCTION_V5 and
                   attempt['input']['review_model']['digest'] == 'sha256:nine'
                   for attempt in attempts)
        for attempt in attempts:
            rows = attempt['input']['rows']
            assert [row['row_id'] for row in rows] == ['r01', 'r02']
            assert set(attempt['schema']['required']) == {'r01', 'r02'}
            assert all(set(row) == {'row_id', 'sentence_id', 'sentence', 'source_spans'}
                       and row['source_spans'] for row in rows)
        assert probe.replay(directory, fixture) == card


def test_v5_missing_or_bad_row_fails_without_retry(harness):
    root, box, _ = harness
    policies = [
        ('missing', lambda payload: {'r01': relation_judgment()}),
        ('unbound', lambda payload: {
            row['row_id']: (relation_judgment('unsupported_assertion', 'funds reached the bank')
                            if 'received the seed funds' in row['sentence'] else
                            relation_judgment()) for row in payload['rows']}),
    ]
    for name, policy in policies:
        box['policy'] = policy
        card = probe.evaluate(FIXTURE, root / f'batch-{name}-qwen3-5-9b', 'qwen3.5:9b',
                              operator_attested=True, contract=probe.BATCH_CONTRACT)
        assert card['decision'] == 'no_go_model_limitation'
        assert card['model_calls'] == 2 == box['models'][-1].calls
        assert card['answers_invalid_or_unbound'] >= 1
        assert probe.replay(root / f'batch-{name}-qwen3-5-9b', FIXTURE) == card


def test_v5_replay_rejects_changed_pin_rows_or_raw_response(harness):
    root, box, _ = harness
    box['policy'] = batch_capable
    changes = [
        ('profile.json', lambda data: data['review_model'].__setitem__('digest', 'sha256:new')),
        ('attempts.json', lambda rows: rows[0]['input']['rows'][0].__setitem__(
            'sentence', 'Different sentence [S2].')),
        ('attempts.json', lambda rows: rows[0].__setitem__(
            'raw_response', rows[0]['raw_response'].replace(
                'supported_as_source_report', 'unsupported_assertion'))),
    ]
    for index, (filename, change) in enumerate(changes):
        name = f'batch-tamper-{index}-qwen3-5-9b'
        probe.evaluate(FIXTURE, root / name, 'qwen3.5:9b',
                       operator_attested=True, contract=probe.BATCH_CONTRACT)
        path = root / name / filename
        data = json.loads(path.read_text())
        change(data)
        path.chmod(0o600)
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match='differs'):
            probe.replay(root / name, FIXTURE)


def test_v5_preflight_rejects_oversized_rows_and_input_without_calls(harness, monkeypatch):
    root, box, _ = harness
    from scripts.evaluate_local_material_review_pair import load_fixture
    rows = probe.probe_rows(load_fixture(FIXTURE), probe.BATCH_CONTRACT)
    pin = {'name': 'qwen3.5:9b', 'digest': 'sha256:nine'}
    with pytest.raises(ValueError, match='four-row synthetic cap'):
        probe.batch_payload('intro_deck', [rows[0]] * 5, pin)
    monkeypatch.setattr(probe, 'MAX_BATCH_INPUT_BYTES', 10)
    with pytest.raises(ValueError, match='bounded input size'):
        probe.evaluate(FIXTURE, root / 'too-large-qwen3-5-9b', 'qwen3.5:9b',
                       operator_attested=True, contract=probe.BATCH_CONTRACT)
    assert not box['models'] and not (root / 'too-large-qwen3-5-9b').exists()


@pytest.fixture
def synthetic_scale_source(tmp_path, monkeypatch):
    source_root = tmp_path / 'material_harness'
    source = source_root / probe.SCALE_SOURCE_NAME
    source.mkdir(parents=True)
    monkeypatch.setattr(probe, 'MATERIAL_ROOT', source_root)
    decks = {
        'intro': [['Funding context',
                   'A registry lists a seed round with unknown status [S1]. '
                   'The company received the seed funds in full [S1].',
                   '[S1] evidence', 'evidence']],
        'pitch': [['Financial context', 'Financials are unavailable [S2].',
                   '[S2] evidence', 'evidence']],
    }
    monkeypatch.setattr(probe, '_slides', lambda path: decks[path.stem])
    pairs = {}
    for stem in ('intro', 'pitch', 'memo'):
        editable = 'docx' if stem == 'memo' else 'pptx'
        for extension in (editable, 'pdf'):
            (source / f'{stem}.{extension}').write_bytes(f'synthetic {stem} {extension}'.encode())
        pairs[stem] = {
            'editable_sha256': hashlib.sha256((source / f'{stem}.{editable}').read_bytes()).hexdigest(),
            'pdf_sha256': hashlib.sha256((source / f'{stem}.pdf').read_bytes()).hexdigest()}
    (source / 'result.json').write_text(json.dumps({
        'state': 'accepted', 'acceptance_scope': 'public_synthetic_diagnostic_only',
        'investor_material_accepted': False, 'pair_reports': pairs}))
    base = {'input_revision': 'synthetic', 'source_hash': 'source',
            'memo_digest': 'memo', 'sections': [
                ['Synthetic memo', 'A registry lists a seed round with unknown status [S1]. '
                 'Financials are unavailable [S2].', '[S1] [S2] evidence']]}
    (source / 'material_request.json').write_text(json.dumps({**base, 'digest': probe.digest(base)}))
    (source / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    return source


def test_v6_scale_probe_two_calls_reports_every_row_without_acceptance(
        harness, synthetic_scale_source):
    root, box, _ = harness
    box['policy'] = scale_capable
    output = root / 'scale-qwen3-5-9b'
    card = probe.evaluate(synthetic_scale_source, output, 'qwen3.5:9b',
                          operator_attested=True, contract=probe.SCALE_CONTRACT)
    assert card['decision'] == 'observed_complete'
    assert card['model_calls'] == 2 == box['models'][-1].calls
    assert card['row_count'] == 3 and card['classification_counts'] == {
        'supported_as_source_report': 2, 'unsupported_assertion': 1,
        'insufficient_evidence': 0}
    assert card['all_rows_classified'] and card['investor_material_accepted'] is False
    assert all(item['reason'] and item['response_id'] and
               item['response_elapsed_seconds'] is not None and item['outcome'] == 'answered'
               for item in card['rows'])
    assert set(card['deck_latency_seconds']) == {'intro_deck', 'pitch_deck'}
    profile = json.loads((output / 'profile.json').read_text())
    attempts = json.loads((output / 'attempts.json').read_text())
    assert profile['source_path'] == str(synthetic_scale_source)
    assert profile['source_digest'] == probe.digest(profile['source_files'])
    assert profile['seconds_per_call'] == 105 and profile['calls_per_deck'] == 1
    assert [attempt['input']['deck'] for attempt in attempts] == ['intro_deck', 'pitch_deck']
    assert [set(attempt['schema']['required']) for attempt in attempts] == [
        {'r01', 'r02'}, {'r01'}]
    assert all(attempt['task'] == probe.SCALE_TASK and
               attempt['input']['review_model']['digest'] == 'sha256:nine' and
               attempt['instruction'] == probe.INSTRUCTION_V6 for attempt in attempts)
    assert probe.replay(output, synthetic_scale_source) == card


def test_v6_source_scope_hash_attestation_and_replay_tamper_fail_closed(
        harness, synthetic_scale_source):
    root, box, _ = harness
    box['policy'] = scale_capable
    output = root / 'scale-guard-qwen3-5-9b'
    with pytest.raises(ValueError, match='operator attestation'):
        probe.evaluate(synthetic_scale_source, output, 'qwen3.5:9b',
                       contract=probe.SCALE_CONTRACT)
    with pytest.raises(ValueError, match='allowlist'):
        probe.evaluate(synthetic_scale_source.parent, output, 'qwen3.5:9b',
                       operator_attested=True, contract=probe.SCALE_CONTRACT)
    assert not output.exists()
    probe.evaluate(synthetic_scale_source, output, 'qwen3.5:9b',
                   operator_attested=True, contract=probe.SCALE_CONTRACT)
    (synthetic_scale_source / 'intro.pptx').write_bytes(b'changed synthetic input')
    with pytest.raises(ValueError, match='artifact hash changed'):
        probe.replay(output, synthetic_scale_source)


def test_v6_preflight_caps_and_invalid_deck_rows(harness, synthetic_scale_source,
                                                  monkeypatch):
    root, box, _ = harness
    pin = {'name': 'qwen3.5:9b', 'digest': 'sha256:nine'}
    row = {'sentence_id': 'intro_deck.slide_1.sentence_1', 'heading': 'Funding',
           'sentence': 'A registry lists a round [S1].', 'source_spans': []}
    with pytest.raises(ValueError, match='16-row cap'):
        probe.scale_payload('intro_deck', [row] * 17, pin, 'digest')
    monkeypatch.setattr(probe, 'MAX_SCALE_INPUT_BYTES', 10)
    with pytest.raises(ValueError, match='bounded input size'):
        probe.evaluate(synthetic_scale_source, root / 'scale-large-qwen3-5-9b',
                       'qwen3.5:9b', operator_attested=True, contract=probe.SCALE_CONTRACT)
    assert not box['models'] and not (root / 'scale-large-qwen3-5-9b').exists()


def test_v6_invalid_intro_response_reports_all_rows_and_never_retries(
        harness, synthetic_scale_source):
    root, box, _ = harness
    box['policy'] = lambda payload: (
        {'r01': relation_judgment()} if payload['deck'] == 'intro_deck'
        else scale_capable(payload))
    output = root / 'scale-invalid-qwen3-5-9b'
    card = probe.evaluate(synthetic_scale_source, output, 'qwen3.5:9b',
                          operator_attested=True, contract=probe.SCALE_CONTRACT)
    assert card['decision'] == 'incomplete_fail_closed' and not card['all_rows_classified']
    assert card['model_calls'] == 2 == box['models'][-1].calls
    assert card['row_count'] == 3
    assert [row['outcome'] for row in card['rows']] == [
        'invalid_answer', 'invalid_answer', 'answered']
    assert probe.replay(output, synthetic_scale_source) == card
