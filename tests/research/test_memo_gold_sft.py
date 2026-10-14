"""Guard a held-out memo corpus without using company or client data."""
import json
import stat

import pytest

from scripts.build_memo_gold_sft import build, validate_target, task_instruction
from agents.inference.model_authorship import digest


@pytest.fixture(autouse=True)
def private_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.build_memo_gold_sft.PRIVATE_DATA', tmp_path)


def _row(number, split, task='memo_content_review'):
    bundle = [{'id': 'S1', 'url': f'https://example.invalid/document-{number}',
               'title': 'Synthetic source', 'version': f'synthetic-v{number}',
               'attribution': 'Synthetic test fixture',
               'passage': f'Synthetic source passage {number} with no financial amount.'}]
    source_set = digest(bundle)
    claim = {'source_id': 'S1', 'quote': bundle[0]['passage'],
             'assertion': 'The retained passage provides information with an outcome still open to independent verification.'}
    section = {'heading': 'Evidence scope', 'analysis':
               'The retained passage provides reported information [S1]. '
               'Further diligence should resolve the open outcome using independent records before any investment decision, while preserving the scope of the reported information.',
               'claims': [claim]}
    memo = {'recommendation': 'defer_pending_evidence',
            'recommendation_reason':
            'The retained passage provides reported information [S1]. '
            'Further independent records are needed to establish the outcome before any investment decision.',
            'recommendation_claims': [claim],
            **{key: section for key in ('investment_thesis', 'business_and_market',
                                        'differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')},
            'unknowns': [{'question': 'Which independent records resolve the open outcome?',
                          'why_it_matters': 'The reported information leaves an outcome open for review.',
                          'evidence_needed': 'Independent records establishing the relevant outcome.'}] * 2}
    input_row = ({'contract': 'memo-content-review-v1',
                  'field_path': 'recommendation_reason',
                  'complete_source_set_digest': source_set,
                  'selected_source_ids': ['S1'],
                  'complete_source_ids': ['S1'], 'omitted_source_ids': [],
                  'sentences': {'s01': f'Synthetic statement {number} stays within the offered source.'},
                  'sources': [{key: bundle[0][key] for key in
                               ('id', 'version', 'attribution', 'passage')}]}
                 if task == 'memo_content_review' else
                 {'contract': 'memo-content-repair-v2',
                  'field_path': 'recommendation_reason',
                  'source_set_digest': source_set,
                  'base_memo_digest': digest(memo),
                  'existing_text': 'The blocked rationale requires an independent rewrite.',
                  'choices': {'c01': {'source_id': 'S1',
                                     'source_version': bundle[0]['version'],
                                     'attribution': bundle[0]['attribution'],
                                     'exact_text': bundle[0]['passage'],
                                     'allowed_numbers': []}},
                  'max_sentences': 3, 'max_sentence_characters': 300,
                  'max_total_characters': 1400})
    target = ({'verdict': 'supported_or_conditional',
               'focus_sentence_id': 's01', 'source_id': 'S1',
               'reason': 'The synthetic sentence stays within its cited passage.'}
              if task == 'memo_content_review' else
              {'replacement_sentences': [{'choice_id': 'c01',
                                          'text': 'The retained passage leaves the outcome open for diligence, so independent records are needed to resolve the question before advancing.'}],
               'recommendation': 'defer_pending_evidence'})
    return {'case_id': f'case-{number}', 'company_key': f'company-{number}',
            **({'base_memo': memo} if task == 'memo_content_repair' else {}),
            'evidence_family_ids': [f'family-{number}'], 'split': split,
            'source_bundle': bundle,
            'task': task, 'input': input_row, 'target': target,
            'provenance': {'rights_status': 'public_training_approved',
                           'source_set_digest': source_set, 'sector': 'synthetic',
                           'reviewer_ids': ['reviewer-a', 'reviewer-b'],
                           'reviewed_at': '2026-10-08T00:00:00+00:00',
                           'adjudication': 'approved'}}


def _source(tmp_path, rows):
    path = tmp_path / 'reviewed.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return path


def test_export_keeps_company_holdout_and_runtime_prompts(tmp_path):
    rows = [_row(1, 'train'), _row(2, 'valid', 'memo_content_repair'),
            _row(3, 'test')]
    output = tmp_path / 'export'
    manifest = build(_source(tmp_path, rows), output)
    assert manifest['counts'] == {'train': 1, 'valid': 1, 'test': 1}
    assert manifest['coverage_thresholds_met'] is False
    assert manifest['release_qualified'] is False
    assert '<|im_start|>system' in json.loads(
        (output / 'train.jsonl').read_text())['text']
    assert 'memo-content-repair-v2' in (output / 'valid.jsonl').read_text()
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600
               for path in output.iterdir())
    with pytest.raises(ValueError, match='already exists'):
        build(_source(tmp_path, rows), output)


def test_company_and_document_family_cannot_cross_splits(tmp_path):
    rows = [_row(1, 'train'), _row(2, 'valid'), _row(3, 'test')]
    rows[1]['company_key'] = rows[0]['company_key']
    with pytest.raises(ValueError, match='Company appears'):
        build(_source(tmp_path, rows), tmp_path / 'export')
    rows[1]['company_key'] = 'company-2'
    rows[1]['evidence_family_ids'] = rows[0]['evidence_family_ids']
    with pytest.raises(ValueError, match='evidence family'):
        build(_source(tmp_path, rows), tmp_path / 'export')


def test_unreviewed_or_numeric_overreach_cannot_be_exported(tmp_path):
    rows = [_row(1, 'train'), _row(2, 'valid', 'memo_content_repair'),
            _row(3, 'test')]
    rows[1]['provenance']['reviewer_ids'] = ['reviewer-a', 'reviewer-a']
    with pytest.raises(ValueError, match='two distinct reviewer'):
        build(_source(tmp_path, rows), tmp_path / 'export')
    rows[1]['provenance']['reviewer_ids'] = ['reviewer-a', 'reviewer-b']
    rows[1]['target']['replacement_sentences'][0]['text'] += ' It claims 99 units.'
    with pytest.raises(ValueError, match='unsupported figure'):
        build(_source(tmp_path, rows), tmp_path / 'export')


def test_direct_build_enforces_private_paths_before_read(tmp_path, monkeypatch):
    private_root = tmp_path / 'private'
    private_root.mkdir()
    monkeypatch.setattr('scripts.build_memo_gold_sft.PRIVATE_DATA', private_root)
    with pytest.raises(ValueError, match='must stay under'):
        build(tmp_path / 'missing.jsonl', private_root / 'export')
    source = _source(private_root, [_row(1, 'train'), _row(2, 'valid'), _row(3, 'test')])
    with pytest.raises(ValueError, match='must stay under'):
        build(source, tmp_path / 'outside')
    (private_root / 'escape').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='must stay under'):
        build(source, private_root / 'escape' / 'export')


@pytest.mark.parametrize('failure', ['sentence_count', 'short_sentence',
                                   'process_prose', 'citation_length', 'unchanged'])
def test_repair_targets_obey_runtime_projection(tmp_path, failure):
    rows = [_row(1, 'train'), _row(2, 'valid', 'memo_content_repair'), _row(3, 'test')]
    row = rows[1]
    payload = row['input']
    item = row['target']['replacement_sentences'][0]
    if failure == 'sentence_count':
        payload['max_sentences'] = 1
        item['text'] = 'The retained passage leaves the outcome open. Further diligence must resolve the missing evidence.'
        error = 'runtime sentence count'
    elif failure == 'short_sentence':
        item['text'] = 'Too short. Further diligence must resolve the missing evidence.'
        error = 'runtime length'
    elif failure == 'process_prose':
        item['text'] = 'The previous memo claimed the outcome without supporting evidence.'
        error = 'process-prose'
    elif failure == 'citation_length':
        item['text'] = 'The retained passage leaves the outcome open for diligence.'
        payload['max_sentence_characters'] = len(item['text'])
        payload['max_total_characters'] = len(item['text'])
        error = 'after citation projection'
    else:
        payload['existing_text'] = item['text'].rstrip('.!? ') + ' [S1].'
        error = 'unchanged'
    with pytest.raises(ValueError, match=error):
        build(_source(tmp_path, rows), tmp_path / 'export')


def test_repair_projected_field_obeys_memo_schema(tmp_path):
    rows = [_row(1, 'train'), _row(2, 'valid', 'memo_content_repair'), _row(3, 'test')]
    rows[1]['target']['replacement_sentences'][0]['text'] = (
        'The retained passage leaves the outcome open for diligence.')
    with pytest.raises(ValueError, match='at least 120 characters'):
        build(_source(tmp_path, rows), tmp_path / 'export')


def test_changed_passage_cannot_keep_old_lineage(tmp_path):
    rows = [_row(1, 'train'), _row(2, 'valid'), _row(3, 'test')]
    rows[1]['input']['sources'][0]['passage'] += ' Altered content.'
    with pytest.raises(ValueError, match='differs from frozen'):
        build(_source(tmp_path, rows), tmp_path / 'export')
    rows[1]['source_bundle'][0]['passage'] += ' Altered content.'
    with pytest.raises(ValueError, match='bundle digest changed'):
        build(_source(tmp_path, rows), tmp_path / 'export')


def test_aliases_cannot_hide_source_leakage(tmp_path):
    rows = [_row(1, 'train'), _row(2, 'valid'), _row(3, 'test')]
    rows[1]['source_bundle'] = rows[0]['source_bundle']
    rows[1]['input']['sources'] = rows[0]['input']['sources']
    source_set = digest(rows[1]['source_bundle'])
    rows[1]['input']['complete_source_set_digest'] = source_set
    rows[1]['provenance']['source_set_digest'] = source_set
    with pytest.raises(ValueError, match='source content appears across splits'):
        build(_source(tmp_path, rows), tmp_path / 'export')


def test_source_author_uses_live_schema_and_rejects_added_number():
    row = _row(1, 'test')
    row['task'] = 'memo_source_author'
    row['input'] = {'component_revision': 'part-a-components-v13',
                    'component': 'business_and_market', 'source_id': 'S1',
                    'quote': row['source_bundle'][0]['passage'],
                    'attribution': row['source_bundle'][0]['attribution'],
                    'sentence_count': 1,
                    'complete_source_set_digest': digest(row['source_bundle'])}
    row['target'] = {'assertion': 'The retained passage reports information without a financial amount.',
                     'sentences': ['The retained passage reports the available information while leaving the financial amount unspecified.']}
    row['instruction'] = task_instruction(row['task'], row['input'])
    assert validate_target(row)[0] == 'memo_source_author'
    row['target']['assertion'] += ' It reports 999 units.'
    with pytest.raises(ValueError, match='exceeds its selected exact quote'):
        validate_target(row)


def test_repair_complete_memo_is_bound(tmp_path):
    rows = [_row(1, 'train'), _row(2, 'valid', 'memo_content_repair'), _row(3, 'test')]
    rows[1]['base_memo']['unknowns'][0]['why_it_matters'] += ' Changed.'
    with pytest.raises(ValueError, match='base memo digest changed'):
        build(_source(tmp_path, rows), tmp_path / 'export')
