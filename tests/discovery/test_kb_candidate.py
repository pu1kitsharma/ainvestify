import json

from agents.discovery.kb_candidate import compare_public_candidates
from public_kb.ingestion import PublicIngestion
from public_kb.claims import ingest_indexed
from public_kb.schedule import set_policy
from datetime import date
import pytest


def test_local_model_must_rewrite_incomplete_candidate_decisions(tmp_path, monkeypatch):
    kb = PublicIngestion(tmp_path / 'kb.sqlite', tmp_path / 'archive')
    ids = []
    for slug in ('alpha', 'beta'):
        source_id = 'startupdb-' + slug
        ids.append(source_id)
        kb.register_source(source_id=source_id,
            url='https://startupdb.com/api/v1/startups/' + slug,
            terms_url='https://startupdb.com/legal', reviewed_at='2026-10-01',
            automated_access=True, retention=True, inference_processing=True,
            investor_reuse=True, enabled=True)
        content = json.dumps({'source_format': 'startupdb_company_v1',
            'company': {'name': slug.title(), 'slug': slug,
                        'headquarters_location': 'Mumbai, India'},
            'funding_history': [{'label': 'Seed', 'date': '2026-01-01',
                                 'amount': {}, 'source_urls': ['https://publisher.example/round']}]})
        digest = kb.stage(source_id, content.encode(), content_type='application/json')
        with kb.conn:
            kb.conn.execute('INSERT INTO fetch_state(source_id,last_sha256) VALUES (?,?)',
                            (source_id, digest))
    kb.publish_pending(lambda *_: None)
    def assessment(decisions, selected=None):
        return json.dumps({'selected_source_id': ids[0] if selected is None else selected,
            'research_rationale': 'The reported seed-stage location warrants a scoped diligence investigation.',
            'unresolved_questions': ['What is the revenue evidence?', 'What confirms customer demand?'],
            'decisions': decisions})
    row = lambda source_id, status: {'source_id': source_id, 'status': status,
        'reason': 'Source-reported Indian seed stage warrants an evidence check.'}
    outputs = [assessment([row(ids[1], 'exclude'), row(ids[1], 'exclude')]),
               assessment([row(ids[0], 'exclude'), row(ids[1], 'exclude')], selected='none'),
               assessment([row(ids[0], 'investigate'), row(ids[1], 'defer')])]
    inputs = []
    def local_chat(**kwargs):
        inputs.append(json.loads(kwargs['messages'][1]['content']))
        return {'message': {'content': outputs.pop(0)}}
    monkeypatch.setattr('agents.discovery.kb_candidate.local_chat', local_chat)
    captured = []
    result = compare_public_candidates(kb, ids, capture=captured.append)
    assert result['assessment']['selected_source_id'] == ids[0]
    assert len(captured) == len(inputs) == 3
    assert captured[0]['raw_response'] == inputs[1]['prior_response']
    assert ids[0] in inputs[1]['review_feedback'][0]
    assert ids[0] in inputs[2]['review_feedback'][-1]
    kb.close()


def test_stale_seed_listing_cannot_be_selected_after_reconciled_series_a(tmp_path, monkeypatch):
    kb = PublicIngestion(tmp_path / 'kb.sqlite', tmp_path / 'archive')
    ids = ['old_listing', 'other_listing']
    for source_id, domain, stage, when in [
        ('old_listing', 'firm.example', 'Seed', '2024-01-01'),
        ('other_listing', 'other.example', 'Seed', '2025-01-01'),
        ('new_announcement', 'firm.example', 'Series A', '2026-08-25')]:
        kb.register_source(source_id=source_id, url='https://' + source_id + '.example/item',
            terms_url='https://terms.example/license', reviewed_at=date.today().isoformat(),
            automated_access=True, retention=True, inference_processing=True,
            investor_reuse=True, enabled=True)
        body = json.dumps({'source_format': 'startupdb_company_v1',
            'company': {'name': source_id, 'domain': domain,
                        'headquarters_location': 'India'},
            'funding_history': [{'label': stage, 'date': when, 'status': 'completed',
                                 'amount': {}, 'source_urls': []}]}).encode()
        digest = kb.stage(source_id, body, content_type='application/json')
        with kb.conn:
            kb.conn.execute('INSERT INTO fetch_state(source_id,last_sha256) VALUES (?,?)',
                            (source_id, digest))
        kb.publish_pending(lambda *_: None)
        ingest_indexed(kb, source_id, digest)
    set_policy(kb, 'other_listing', 'profile')
    response = json.dumps({'selected_source_id': ids[0],
        'research_rationale': 'A historical seed record warrants investigation with a full funding chronology.',
        'unresolved_questions': ['What is the current financing status?', 'What is the revenue?'],
        'decisions': [{'source_id': item, 'status': 'investigate' if item == ids[0] else 'defer',
                       'reason': 'Source reported evidence needs additional review before diligence.'}
                      for item in ids]})
    seen = []
    def fake_chat(**kwargs):
        seen.append(json.loads(kwargs['messages'][1]['content']))
        return {'message': {'content': response}}
    monkeypatch.setattr('agents.discovery.kb_candidate.local_chat', fake_chat)
    with pytest.raises(ValueError, match='Reconciled current company history'):
        compare_public_candidates(kb, ids)
    assert seen[0]['candidates'][0]['reconciled_current']['stage'] == 'Series A'
    assert len(seen[0]['candidates'][0]['claim_history']) == 2
    assert seen[0]['candidates'][1]['reconciled_current']['refresh_gaps'] == ['other_listing']
    alternate = json.loads(response)
    alternate['selected_source_id'] = ids[1]
    alternate['decisions'] = [{'source_id': item,
        'status': 'investigate' if item == ids[1] else 'defer',
        'reason': 'Source reported evidence needs additional review before diligence.'}
        for item in ids]
    monkeypatch.setattr('agents.discovery.kb_candidate.local_chat',
                        lambda **kwargs: {'message': {'content': json.dumps(alternate)}})
    with pytest.raises(ValueError, match='overdue, failed or untracked'):
        compare_public_candidates(kb, ids)
    kb.close()
