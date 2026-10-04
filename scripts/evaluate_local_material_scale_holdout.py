"""Independent bounded defect/control holdout for compact local material review.

The synthetic fixture is test-only. Its expected labels never enter model input.
Two digest-pinned local calls are made, one per deck, with no retries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from pydantic import ValidationError

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest, recorded_call, response_answer
from agents.preparation.preparation_budget import PreparationBudget, PreparationBudgetExceeded, preparation_budget
from scripts.evaluate_local_assertion_relation_probe import BATCH_SECONDS, OUTPUT_ROOT, SCALE_OPTIONS, SCOPE
from scripts.evaluate_local_material_scale_compact import (
    INSTRUCTION, compact_payload, compact_schema,
)
from scripts.evaluate_local_material_review_harness import review_pin
from scripts.evaluate_local_memo_harness import installed_models

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/material_review/compact_scale_holdout_v1.json'
CONTRACT = 'assertion-relation-compact-holdout-v1'
TASK = 'assertion_relation_compact_holdout'
EXPECTED = {'supported_as_source_report', 'unsupported_assertion'}


def fixture():
    raw = FIXTURE.read_bytes()
    data = json.loads(raw)
    if data.get('kind') != 'synthetic_material_relation_holdout' or data.get('version') != 1:
        raise ValueError('Holdout fixture version mismatch')
    if set(data.get('decks', {})) != {'intro_deck', 'pitch_deck'}:
        raise ValueError('Holdout requires exactly two decks')
    for deck, rows in data['decks'].items():
        if len(rows) != 3 or len({r['sentence_id'] for r in rows}) != 3:
            raise ValueError('Holdout deck requires three distinct rows')
        if any(r.get('expected') not in EXPECTED or not r.get('source_spans') for r in rows):
            raise ValueError('Holdout expected label or evidence missing')
    return data, hashlib.sha256(raw).hexdigest()


def payload(deck, rows, pin, fixture_hash):
    stripped = [{key: val for key, val in row.items() if key != 'expected'} for row in rows]
    result = compact_payload(deck, stripped, pin, fixture_hash)
    result['probe_contract'] = CONTRACT
    return result


def score(data, attempts, pin, fixture_hash, stopped=None):
    scored = []
    for deck, rows in data['decks'].items():
        attempt = next((a for a in attempts if a.get('input', {}).get('deck') == deck), None)
        answers = attempt.get('answer') if attempt and isinstance(attempt.get('answer'), dict) else {}
        for index, row in enumerate(rows, 1):
            answer = answers.get(f'r{index:02d}') or {}
            label, clause = answer.get('classification'), answer.get('challenged_clause')
            if not attempt or not attempt.get('raw_response'):
                outcome = 'no_answer'
            elif attempt.get('error') or not answer:
                outcome = 'invalid_answer'
            elif ((label == 'unsupported_assertion' and not (isinstance(clause, str) and
                    len(clause.strip()) >= 4 and clause in row['sentence'])) or
                  (label != 'unsupported_assertion' and clause is not None)):
                outcome = 'unbound_challenged_clause'
            else:
                outcome = 'answered'
            scored.append({'deck': deck, 'sentence_id': row['sentence_id'],
                           'expected': row['expected'], 'classification': label,
                           'challenged_clause': clause, 'outcome': outcome,
                           'passed': outcome == 'answered' and label == row['expected'],
                           'response_id': attempt.get('id') if attempt else None})
    go = stopped is None and len(attempts) == 2 and all(r['passed'] for r in scored)
    return {'kind': 'assertion_relation_compact_holdout', 'probe_contract': CONTRACT,
            'fixture_sha256': fixture_hash, 'review_model': pin, 'stopped': stopped,
            'model_calls': len(attempts), 'rows': scored, 'decision': 'go' if go else 'no_go',
            'calls_per_deck': 1, 'retries': 0,
            'score_limits': 'One independent six-row synthetic holdout; no investor material approval.',
            **SCOPE}


def replay(output: Path):
    data, fixture_hash = fixture()
    profile = json.loads((output / 'profile.json').read_text())
    pin = profile['review_model']
    expected = {deck: (payload(deck, rows, pin, fixture_hash),
                       compact_schema(deck, rows).model_json_schema())
                for deck, rows in data['decks'].items()}
    if (profile.get('probe_contract') != CONTRACT or profile.get('fixture_sha256') != fixture_hash
            or profile.get('instruction_sha256') != digest(INSTRUCTION)
            or profile.get('deck_schema_sha256') != {d: digest(s) for d, (_, s) in expected.items()}
            or pin.get('options') != SCALE_OPTIONS[False]
            or profile.get('seconds_per_call') != BATCH_SECONDS
            or profile.get('calls_per_deck') != 1 or profile.get('retries') != 0
            or any(profile.get(k) != v for k, v in SCOPE.items())):
        raise ValueError('Holdout profile differs from frozen contract')
    attempts = json.loads((output / 'attempts.json').read_text())
    if len(attempts) > 2:
        raise ValueError('Holdout exceeded two recorded calls')
    for index, attempt in enumerate(attempts):
        deck = tuple(expected)[index]
        input_, schema = expected[deck]
        if (attempt.get('id') != f'response_{index + 1}' or attempt.get('task') != TASK or
                attempt.get('input') != input_ or attempt.get('instruction') != INSTRUCTION or
                attempt.get('schema') != schema or attempt.get('model') != pin['name'] or
                any(attempt.get('routing', {}).get(k) != v for k, v in pin['options'].items()) or
                digest(attempt.get('raw_response')) != attempt.get('response_hash')):
            raise ValueError('Holdout attempt differs from frozen contract')
        if not attempt.get('error'):
            answer = response_answer(attempts, attempt['id'])
            if compact_schema(deck, data['decks'][deck]).model_validate(answer).model_dump(mode='json') != answer:
                raise ValueError('Holdout answer differs from frozen schema')
    return score(data, attempts, pin, fixture_hash, profile.get('stopped'))


def evaluate(output: Path, review_model: str, *, operator_attested=False):
    if not operator_attested:
        raise ValueError('Synthetic holdout requires operator attestation')
    output = Path(output).resolve()
    if not output.is_relative_to(OUTPUT_ROOT.resolve()) or output == OUTPUT_ROOT.resolve():
        raise ValueError('Output must be within ignored probe root')
    data, fixture_hash = fixture()
    pin, pin_record = review_pin(review_model, review_model, installed_models(), output)
    pin['options'] = pin_record['options'] = dict(SCALE_OPTIONS[False])
    payloads = {deck: payload(deck, rows, pin, fixture_hash)
                for deck, rows in data['decks'].items()}
    schemas = {deck: compact_schema(deck, rows) for deck, rows in data['decks'].items()}
    model = LocalModel(pin['name'], **SCALE_OPTIONS[False])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700, exist_ok=False)
    attempts, attempts_file = [], output / 'attempts.json'

    def save():
        temp = attempts_file.with_suffix('.json.tmp')
        temp.write_text(json.dumps(attempts, ensure_ascii=False))
        temp.replace(attempts_file)

    stopped = None
    for deck in data['decks']:
        if installed_models().get(pin['name']) != pin['digest']:
            stopped = 'installed_model_digest_changed'
            break
        budget = PreparationBudget(BATCH_SECONDS, max_calls=1, max_requests=1)
        try:
            with preparation_budget(budget):
                recorded_call(model, TASK, INSTRUCTION, payloads[deck], schemas[deck], attempts, save)
        except (PreparationBudgetExceeded, ValidationError, ValueError, RuntimeError):
            pass
    save()
    profile = {'kind': 'assertion_relation_compact_holdout', 'probe_contract': CONTRACT,
               'fixture_sha256': fixture_hash, 'review_model': pin_record,
               'stopped': stopped, 'calls_per_deck': 1, 'retries': 0,
               'seconds_per_call': BATCH_SECONDS,
               'instruction_sha256': digest(INSTRUCTION),
               'deck_schema_sha256': {d: digest(s.model_json_schema()) for d, s in schemas.items()},
               **SCOPE}
    (output / 'profile.json').write_text(json.dumps(profile, ensure_ascii=False, indent=1))
    card = score(data, attempts, pin_record, fixture_hash, stopped)
    (output / 'scorecard.json').write_text(json.dumps(card, ensure_ascii=False, indent=1))
    for name in ('attempts.json', 'profile.json'):
        os.chmod(output / name, 0o400)
    if replay(output) != card:
        raise ValueError('Holdout score differs from raw replay')
    return card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--review-model', required=True)
    parser.add_argument('--operator-attested-public-or-synthetic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(evaluate(args.output, args.review_model,
                              operator_attested=args.operator_attested_public_or_synthetic), indent=1))


if __name__ == '__main__':
    main()
