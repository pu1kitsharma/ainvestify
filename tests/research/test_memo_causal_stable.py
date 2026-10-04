"""Stable per-row causal lineage over a changed synthetic memo."""
import copy
import json

from agents.inference.model_authorship import digest
from agents.research import memo_causal_review as causal
from tests.research.test_memo_causal_review import sample


def test_prior_exact_clear_rows_reused_and_changed_row_gets_single_call():
    memo, sources = sample()
    old_contract = {'version': causal.CONTRACT_V2,
                    'model_name': 'qwen3:14b', 'model_digest': 'a' * 64}
    attempts = []
    for number, (_, rows, payload, schema) in enumerate(
            causal.frozen_calls(memo, sources, old_contract), 1):
        answer = {row['row_id']: {
            'relation': 'no_unsupported_consequence',
            'focus_clause_id': 'c00',
            'premise_source_ids': row['premise_ids'],
            'reason': 'The cited sentence remains an attributed report or conditional diligence action.'}
            for row in rows}
        raw = json.dumps(answer)
        attempts.append({'id': f'prior_v2_response_{number}',
                         'original_response_id': f'response_{number}',
                         'task': causal.TASK_V2,
                         'input': payload, 'schema': schema.model_json_schema(),
                         'instruction': causal.INSTRUCTION_V2, 'model': 'qwen3:14b',
                         'routing': {'model': 'qwen3:14b', **causal.OPTIONS},
                         'raw_response': raw, 'response_hash': digest(raw),
                         'answer': answer})
    revised = copy.deepcopy(memo)
    revised['business_and_market']['analysis'] = (
        'The synthetic registry entry reports financing but does not confirm whether the transaction closed or whether operating cash is available [S1]. '
        'The diligence team should request dated transaction records before '
        'relying on the reported round [S1].')
    lineage = {'prior_memo_digest': digest(memo),
               'prior_response_ids': [row['id'] for row in attempts],
               'original_response_ids': [row['original_response_id'] for row in attempts],
               'prior_response_hashes': [row['response_hash'] for row in attempts],
               'prior_result_sha256': 'b' * 64}
    contract = {'version': causal.CONTRACT_V3, 'model_name': 'qwen3:14b',
                'model_digest': 'a' * 64, 'prior_lineage': lineage}
    result, next_call = causal.evaluate_attempts(revised, sources, attempts, contract)
    assert result is None
    assert next_call[0]['field'] == 'business_and_market'
    assert len([call for call in causal._v3_calls(revised, sources, contract)
                if causal._stable_key(call[1], call[2]) not in
                causal._prior_v2_judgments(sources, attempts, contract)[0]]) == 2
    attempts[0]['response_hash'] = '0' * 64
    try:
        causal.evaluate_attempts(revised, sources, attempts, contract)
    except ValueError as exc:
        assert 'raw' in str(exc) or 'lineage' in str(exc)
    else:
        raise AssertionError('tampered prior raw was accepted')
