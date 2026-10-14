"""Private queue import must preserve saved answers and pending labels."""
import json
import stat

from agents.inference.model_authorship import digest
from agents.research import memo_content_review as review
from scripts import build_memo_gold_sft as gold
from scripts import prepare_memo_training_candidates as intake
from tests.research.test_memo_gold_sft import _row


def test_import_rejects_tampered_answer_and_keeps_labels_pending(tmp_path, monkeypatch):
    runs, private = tmp_path / 'runs', tmp_path / 'data'
    runs.mkdir()
    private.mkdir()
    monkeypatch.setattr(intake, 'PRIVATE_RUNS', runs)
    monkeypatch.setattr(gold, 'PRIVATE_DATA', private)
    case = _row(1, 'test')
    case['input'].update(context={}, review_model={'name': 'synthetic-local', 'digest': 'a' * 64})
    request = {'sources': case['source_bundle'],
               'review_contract': {'model_name': 'synthetic-local'},
               'author_pin': {'name': 'synthetic-local'}}
    (runs / 'content_request.json').write_text(json.dumps({**request, 'digest': digest(request)}))
    raw = json.dumps(case['target'])
    attempt = {'id': 'r1', 'task': review.TASK, 'instruction': review.INSTRUCTION,
               'input': case['input'], 'schema': gold._schema(case['task'], case['input']).model_json_schema(),
               'answer': case['target'], 'raw_response': raw,
               'response_hash': digest(raw), 'model': 'synthetic-local'}
    tampered = {**attempt, 'id': 'r2', 'answer': {**case['target'], 'verdict': 'unsupported'}}
    (runs / 'content_review_attempts.json').write_text(json.dumps([attempt, tampered]))
    out = private / 'queue'
    result = intake.prepare([runs], out, company_key='opaque-private-company',
                            sector='synthetic', approval_id='user-approval', approved_on='2026-10-08')
    assert result['candidate_counts'] == {'memo_content_review': 1}
    assert result['counts']['replay_or_target_validation_failed'] == 1
    candidate = json.loads((out / 'candidates.jsonl').read_text())
    assert candidate['target'] == case['target']
    assert candidate['split'] == 'test'
    assert candidate['provenance']['adjudication'] == 'pending'
    assert candidate['provenance']['reviewer_ids'] == []
    assert result['trainable_examples'] == 0
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in out.iterdir())
