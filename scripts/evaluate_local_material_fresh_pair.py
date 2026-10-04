"""Three-call compact review of one frozen synthetic draft and a planted defect.

This does not alter the recorded draft. The unchanged pitch deck is judged once
and shared by the control/defect cases. Expectations never enter model inputs.
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
from agents.research.material_review import compact_review_payload
from agents.research.material_slides import render_sections, replay_material_rows
from scripts.evaluate_local_assertion_relation_probe import BATCH_SECONDS, OUTPUT_ROOT, SCALE_OPTIONS, SCOPE
from scripts.evaluate_local_material_scale_compact import INSTRUCTION, compact_payload, compact_schema
from scripts.evaluate_local_material_review_harness import MATERIAL_ROOT, review_pin
from scripts.evaluate_local_memo_harness import installed_models

SOURCE_NAME = '2026-10-04-source-gap-9b-v5'
SOURCE_PROFILES = {
    SOURCE_NAME: {'contract': 'evidence_v5', 'funding_slide': 1},
    '2026-10-04-complete-source-9b-v7': {'contract': 'evidence_v7', 'funding_slide': 2},
}
CONTRACT = 'assertion-relation-fresh-pair-v1'
CONTRACT_V2 = 'assertion-relation-fresh-pair-v2-citation-attached'
TASK = 'assertion_relation_fresh_pair'
TASK_V2 = 'assertion_relation_fresh_pair_v2'
PLANTED_SENTENCE = ('Harborline Systems received the full INR 4 crore from the July 2026 '
                    'Pre-Seed round [S2].')
FILES = ('material_request.json', 'material_attempts.json', 'model.json', 'result.json')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(old, decks, source_digest, *, extraction=None):
    base = {'review_contract': 'semantic_v10', 'input_revision': old['input_revision'],
            'source_hash': old['source_hash'], 'memo_digest': old['memo_digest'],
            'material_digest': source_digest, 'memo_sections': old['sections'],
            'decks': decks, 'review_model': {}}
    if extraction is not None:
        base['evidence_extraction'] = extraction
    compact = compact_review_payload({**base, 'digest': digest(base)})
    grouped = {'intro_deck': [], 'pitch_deck': []}
    for choice in compact['sentence_choices']:
        grouped[choice['deck']].append({
            'sentence_id': choice['id'], 'heading': choice['heading'],
            'sentence': choice['sentence'],
            'source_spans': [compact['memo_evidence'][i]
                             for i in choice['memo_evidence_indices']]})
    return grouped


def load_source(path: Path, *, recorded_files=None, extraction=None):
    path = Path(path).resolve()
    source_profile = SOURCE_PROFILES.get(path.name)
    if source_profile is None or path != (MATERIAL_ROOT / path.name).resolve():
        raise ValueError('Fresh pair source outside frozen synthetic allowlist')
    files = {name: _sha(path / name) for name in FILES}
    if recorded_files is not None and files != recorded_files:
        raise ValueError('Frozen fresh draft files changed')
    old = json.loads((path / 'material_request.json').read_text())
    if old.get('digest') != digest({k: v for k, v in old.items() if k != 'digest'}) or \
            old.get('replay_contracts') != {deck: source_profile['contract'] for deck in (
                'intro_deck', 'pitch_deck')}:
        raise ValueError('Fresh draft request contract changed')
    result = json.loads((path / 'result.json').read_text())
    if (result.get('state') != 'accepted' or result.get('source_hash') != old['source_hash']
            or result.get('memo_digest') != old['memo_digest']):
        raise ValueError('Fresh draft is not accepted under its source scope')
    attempts = json.loads((path / 'material_attempts.json').read_text())
    model = json.loads((path / 'model.json').read_text())['profiles']['draft']
    sections = {}
    for deck in ('intro_deck', 'pitch_deck'):
        payload = {k: old[k] for k in ('input_revision', 'source_hash', 'memo_digest', 'sections')}
        replayed = replay_material_rows(deck, {**payload, 'kind': deck}, attempts,
                                        old['sections'], model_name=model,
                                        contract_version=source_profile['contract'])
        if (replayed['state'] != 'accepted' or
                replayed['response_ids'] != result['decks'][deck]['response_ids']):
            raise ValueError('Fresh deck differs from recorded local responses')
        rendered = render_sections(replayed['spec'], old['sections'])
        if [list(section) for section in rendered] != result['decks'][deck]['sections']:
            raise ValueError('Fresh deck sections differ from model response')
        sections[deck] = result['decks'][deck]['sections']
    control = _rows(old, sections, digest(files), extraction=extraction)
    defect_decks = json.loads(json.dumps(sections))
    slide_index = source_profile['funding_slide']
    heading, body, bibliography, layout = defect_decks['intro_deck'][slide_index]
    if heading != 'Funding History' or '[S2]' not in body:
        raise ValueError('Planted defect has no pinned synthetic funding slide')
    defect_decks['intro_deck'][slide_index] = [heading, body + ' ' + PLANTED_SENTENCE,
                                               bibliography, layout]
    defect = _rows(old, defect_decks, digest(files), extraction=extraction)
    planted = [r for r in defect['intro_deck'] if r['sentence'] == PLANTED_SENTENCE]
    if len(planted) != 1 or len(defect['intro_deck']) != len(control['intro_deck']) + 1:
        raise ValueError('Planted defect is not a single new sentence')
    for deck in control:
        if ([(r['sentence_id'], r['sentence']) for r in control[deck]] !=
            [(r['sentence_id'], r['sentence']) for r in defect[deck]
             if r['sentence'] != PLANTED_SENTENCE]):
            raise ValueError('Defect changed an original sentence')
    return {'path': str(path), 'source_files': files, 'source_digest': digest(files),
            'draft_model': model, 'control_rows': control,
            'defect_intro_rows': defect['intro_deck'],
            'planted_sentence_id': planted[0]['sentence_id']}


def calls(source, pin, *, contract=CONTRACT):
    names = ('control_intro', 'control_pitch', 'defect_intro')
    rows = (source['control_rows']['intro_deck'],
            source['control_rows']['pitch_deck'], source['defect_intro_rows'])
    decks = ('intro_deck', 'pitch_deck', 'intro_deck')
    result = []
    for name, deck, row_set in zip(names, decks, rows):
        payload = compact_payload(deck, row_set, pin, source['source_digest'])
        payload['probe_contract'] = contract
        payload['case'] = name
        result.append((name, payload, compact_schema(deck, row_set)))
    return result


def score(source, attempts, pin, stopped=None, *, contract=CONTRACT):
    by_case = {a.get('input', {}).get('case'): a for a in attempts}
    scored = {}
    for case, rows in (('control_intro', source['control_rows']['intro_deck']),
                       ('control_pitch', source['control_rows']['pitch_deck']),
                       ('defect_intro', source['defect_intro_rows'])):
        attempt = by_case.get(case)
        answers = attempt.get('answer') if attempt and isinstance(attempt.get('answer'), dict) else {}
        scored[case] = []
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
            scored[case].append({'sentence_id': row['sentence_id'], 'heading': row['heading'],
                                 'sentence': row['sentence'], 'classification': label,
                                 'challenged_clause': clause, 'reason': answer.get('reason'),
                                 'outcome': outcome})
    control_by_id = {r['sentence_id']: r for r in scored['control_intro']}
    defect_by_id = {r['sentence_id']: r for r in scored['defect_intro']}
    planted = defect_by_id[source['planted_sentence_id']]
    unchanged_same = all(defect_by_id[rid]['classification'] == row['classification']
                         and defect_by_id[rid]['outcome'] == row['outcome']
                         for rid, row in control_by_id.items())
    complete = stopped is None and len(attempts) == 3 and all(
        row['outcome'] == 'answered' for deck in scored.values() for row in deck)
    pair_go = complete and unchanged_same and planted['classification'] == 'unsupported_assertion'
    return {'kind': 'assertion_relation_fresh_pair', 'probe_contract': contract,
            'source_digest': source['source_digest'], 'review_model': pin, 'stopped': stopped,
            'cases': scored, 'planted_sentence_id': source['planted_sentence_id'],
            'unchanged_intro_labels_stable': unchanged_same,
            'unchanged_pitch_shares_one_judgment': True,
            'model_calls': len(attempts), 'decision': 'pair_go' if pair_go else 'pair_no_go',
            'score_limits': 'Synthetic text-only draft and one planted defect; no content, '
                            'financial, visual, or investor acceptance.', **SCOPE}


def strict_scorecard(differential: dict) -> dict:
    """Versioned aggregate requiring a clean control, without changing saved v1/v2 cards.

    The older `pair_go` was only a differential result. This derivative binds
    to that exact replayed card and fails closed on any unsupported/unknown
    clean control row. It is not a substitute for independent content review.
    """
    controls = [*differential['cases']['control_intro'],
                *differential['cases']['control_pitch']]
    blocked = [row['sentence_id'] for row in controls if
               row['outcome'] != 'answered' or
               row['classification'] != 'supported_as_source_report']
    planted = next(row for row in differential['cases']['defect_intro']
                   if row['sentence_id'] == differential['planted_sentence_id'])
    strict_go = (differential['decision'] == 'pair_go' and not blocked and
                 planted['classification'] == 'unsupported_assertion' and
                 planted['outcome'] == 'answered')
    return {**differential, 'derivation_contract': 'strict-clean-control-v1',
            'differential_decision': differential['decision'],
            'clean_control_blocked_sentence_ids': blocked,
            'clean_control_all_supported': not blocked,
            'decision': 'pair_go' if strict_go else 'pair_no_go',
            'score_limits': 'Strict synthetic defect/control criterion on exact replayed '
                            'rows; no independent content, financial, visual, or release acceptance.'}


def replay(output: Path):
    profile = json.loads((output / 'profile.json').read_text())
    contract = profile.get('probe_contract')
    if contract not in (CONTRACT, CONTRACT_V2):
        raise ValueError('Unknown fresh pair contract')
    extraction = 'trailing_citation_v1' if contract == CONTRACT_V2 else None
    source = load_source(Path(profile['source_path']), recorded_files=profile['source_files'],
                         extraction=extraction)
    pin = profile['review_model']
    expected = calls(source, pin, contract=contract)
    if (profile.get('source_digest') != source['source_digest'] or
            profile.get('instruction_sha256') != digest(INSTRUCTION) or
            profile.get('schema_sha256') != {name: digest(schema.model_json_schema())
                                             for name, _, schema in expected} or
            pin.get('options') != SCALE_OPTIONS[False] or
            profile.get('seconds_per_call') != BATCH_SECONDS or
            profile.get('max_calls') != 3 or profile.get('retries') != 0 or
            any(profile.get(k) != v for k, v in SCOPE.items())):
        raise ValueError('Fresh pair profile differs from frozen contract')
    attempts = json.loads((output / 'attempts.json').read_text())
    if len(attempts) > 3:
        raise ValueError('Fresh pair exceeded three calls')
    for index, attempt in enumerate(attempts):
        _, payload, schema = expected[index]
        if (attempt.get('id') != f'response_{index + 1}' or
                attempt.get('task') != (TASK_V2 if contract == CONTRACT_V2 else TASK) or
                attempt.get('input') != payload or attempt.get('instruction') != INSTRUCTION or
                attempt.get('schema') != schema.model_json_schema() or
                attempt.get('model') != pin['name'] or
                any(attempt.get('routing', {}).get(k) != v for k, v in pin['options'].items()) or
                digest(attempt.get('raw_response')) != attempt.get('response_hash')):
            raise ValueError('Fresh pair attempt differs from frozen contract')
        if not attempt.get('error'):
            answer = response_answer(attempts, attempt['id'])
            if schema.model_validate(answer).model_dump(mode='json') != answer:
                raise ValueError('Fresh pair answer differs from schema')
    return score(source, attempts, pin, profile.get('stopped'), contract=contract)


def evaluate(path: Path, output: Path, review_model: str, *, operator_attested=False,
             contract=CONTRACT):
    if contract not in (CONTRACT, CONTRACT_V2):
        raise ValueError('Unknown fresh pair contract')
    if not operator_attested:
        raise ValueError('Synthetic fresh pair requires operator attestation')
    output = Path(output).resolve()
    if not output.is_relative_to(OUTPUT_ROOT.resolve()) or output == OUTPUT_ROOT.resolve():
        raise ValueError('Output must be under ignored probe root')
    source = load_source(path, extraction='trailing_citation_v1'
                         if contract == CONTRACT_V2 else None)
    pin, pin_record = review_pin(source['draft_model'], review_model, installed_models(), output)
    pin['options'] = pin_record['options'] = dict(SCALE_OPTIONS[False])
    expected = calls(source, pin, contract=contract)
    model = LocalModel(pin['name'], **SCALE_OPTIONS[False])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700, exist_ok=False)
    attempts, attempts_file = [], output / 'attempts.json'

    def save():
        temp = attempts_file.with_suffix('.json.tmp')
        temp.write_text(json.dumps(attempts, ensure_ascii=False))
        temp.replace(attempts_file)

    stopped = None
    for _, payload, schema in expected:
        if installed_models().get(pin['name']) != pin['digest']:
            stopped = 'installed_model_digest_changed'
            break
        budget = PreparationBudget(BATCH_SECONDS, max_calls=1, max_requests=1)
        try:
            with preparation_budget(budget):
                recorded_call(model, TASK_V2 if contract == CONTRACT_V2 else TASK,
                              INSTRUCTION, payload, schema, attempts, save)
        except (PreparationBudgetExceeded, ValidationError, ValueError, RuntimeError):
            pass
    save()
    load_source(path, recorded_files=source['source_files'],
                extraction='trailing_citation_v1' if contract == CONTRACT_V2 else None)
    profile = {'kind': 'assertion_relation_fresh_pair', 'probe_contract': contract,
               'source_path': source['path'], 'source_files': source['source_files'],
               'source_digest': source['source_digest'], 'review_model': pin_record,
               'stopped': stopped, 'max_calls': 3, 'retries': 0,
               'seconds_per_call': BATCH_SECONDS,
               'instruction_sha256': digest(INSTRUCTION),
               'schema_sha256': {name: digest(schema.model_json_schema())
                                 for name, _, schema in expected}, **SCOPE}
    (output / 'profile.json').write_text(json.dumps(profile, indent=1))
    card = score(source, attempts, pin_record, stopped, contract=contract)
    (output / 'scorecard.json').write_text(json.dumps(card, indent=1))
    for name in ('attempts.json', 'profile.json'):
        os.chmod(output / name, 0o400)
    if replay(output) != card:
        raise ValueError('Fresh pair score differs from exact raw replay')
    return card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('material_dir', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--review-model', required=True)
    parser.add_argument('--contract', choices=(CONTRACT, CONTRACT_V2), default=CONTRACT)
    parser.add_argument('--operator-attested-public-or-synthetic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(evaluate(args.material_dir, args.output, args.review_model,
                              operator_attested=args.operator_attested_public_or_synthetic,
                              contract=args.contract), indent=1))


if __name__ == '__main__':
    main()
