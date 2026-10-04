"""Reader memo layout must still offer substantive, source-bound review spans."""

import json

from agents.inference.model_authorship import digest
from agents.research.investment_memo import renderable_sections
from agents.research.material_review import compact_review_payload
from delivery import material_review_stage as stage
from tests.research.test_memo_section_projection import (SOURCES, QUOTE, ASSERTION,
                                                         accepted, accepted_v2)


def request(sections):
    return {'review_contract': 'semantic_v10', 'memo_section_projection': 'reader_v1',
            'memo_sections': sections,
            'decks': {
                'intro_deck': [('Product', 'The source reports a scheduling pilot [S1].')],
                'pitch_deck': [('Financing',
                                'A registry lists a seed financing entry with unknown status [S2].')]},
            'input_revision': 'synthetic', 'source_hash': 'source', 'memo_digest': 'memo',
            'material_digest': 'material', 'review_model': {}, 'digest': 'synthetic'}


def test_reader_v1_memo_feeds_complete_substantive_evidence_to_deck_review():
    result, attempts, _ = accepted()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v1')
    compact = compact_review_payload(request(sections))
    spans = compact['memo_evidence']
    assert len(compact['sentence_choices']) == 2
    for choice in compact['sentence_choices']:
        assert choice['memo_evidence_indices']
        assert any('source reports a scheduling tool' in spans[index]['exact_span']
                   or 'registry lists a seed financing entry' in spans[index]['exact_span']
                   for index in choice['memo_evidence_indices'])
    assert all(not sections[span['section_index']][0].startswith('Sources and retained versions')
               for span in spans)
    assert all('https://' not in span['exact_span'] for span in spans)


def test_bibliography_sentence_cannot_be_selected_as_substantive_evidence():
    sections = [
        ('Product', '[S1] The source reports a scheduling tool for clinics.', '[S1] Source'),
        ('Financing', '[S2] A registry lists a Seed entry with unknown status.', '[S2] Source'),
        ('Sources and retained versions',
         '[S1] https://example.invalid/source | version v1. The contract is signed [S1].\n'
         '[S2] https://example.invalid/registry | version v1. The funding is complete [S2].', ''),
    ]
    spans = compact_review_payload(request(sections))['memo_evidence']
    assert len(spans) == 2
    assert {span['exact_span'] for span in spans} == {
        '[S1] The source reports a scheduling tool for clinics.',
        '[S2] A registry lists a Seed entry with unknown status.'}


def test_fresh_reader_review_marks_projection_and_saved_older_request_stays_exact(
        tmp_path, monkeypatch):
    result, attempts, _ = accepted()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v1')
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    monkeypatch.setattr(stage, 'validate_material_checkpoint', lambda job, memo, material: material)
    monkeypatch.setattr(stage, '_installed_digest', lambda name: 'synthetic-model-digest')
    memo = {'source_hash': 'source', 'sections': sections, 'section_projection': 'reader_v1'}
    material = {'memo_digest': 'memo', 'decks': {
        deck: {'sections': rows} for deck, rows in request(sections)['decks'].items()}}
    fresh = stage._review_request({'input_revision': 'synthetic'}, memo, material, tmp_path)
    assert fresh['memo_section_projection'] == 'reader_v1'
    assert fresh['digest'] == digest({k: v for k, v in fresh.items() if k != 'digest'})
    older = {key: value for key, value in fresh.items() if key not in (
        'memo_section_projection', 'digest')}
    older['digest'] = digest(older)
    (tmp_path / 'material_review_request.json').write_text(json.dumps(older))
    replayed = stage._review_request({'input_revision': 'synthetic'}, memo, material, tmp_path)
    assert replayed == older


def test_versioned_extraction_binds_trailing_citation_to_exact_prior_claim():
    sections = [
        ('Product', 'The company builds scheduling software for freight teams. [S1] '
         'The customer count remains unverified. [S1]', '[S1] Product source'),
        ('Funding', 'A registry lists a Seed round with unknown status. [S2] '
         'No cash receipt is shown. [S2]', '[S2] Registry source'),
    ]
    candidate = request(sections)
    candidate['evidence_extraction'] = 'trailing_citation_v1'
    spans = compact_review_payload(candidate)['memo_evidence']
    exact = {span['exact_span'] for span in spans}
    assert 'The company builds scheduling software for freight teams. [S1]' in exact
    assert 'A registry lists a Seed round with unknown status. [S2]' in exact
    assert all(span in '\n'.join(section[1] for section in sections) for span in exact)
    assert any('[S1]' in span for span in exact)
    assert any('[S2]' in span for span in exact)
    # Recorded v10 requests without the extraction marker retain their old span set.
    old = compact_review_payload(request(sections))['memo_evidence']
    assert old != spans


def test_reader_v2_review_pairs_model_claims_with_retained_quotes_and_skips_bibliography():
    result, attempts, _ = accepted_v2()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    candidate = request(sections)
    candidate.update(memo_section_projection='reader_v2',
                     evidence_extraction='reader_v2_claim_pair_v1')
    compact = compact_review_payload(candidate)
    spans = compact['memo_evidence']
    assert len(compact['sentence_choices']) == 2
    assert all(choice['memo_evidence_indices'] for choice in compact['sentence_choices'])
    appendix = [(index, section[1]) for index, section in enumerate(sections)
                if section[0].startswith('Evidence appendix')]
    assert appendix
    assert all(not sections[span['section_index']][0].startswith('Sources and retained versions')
               for span in spans)
    paired = [span for span in spans if sections[span['section_index']][0].startswith(
        'Evidence appendix')]
    assert any('[S1] The source reports a scheduling tool' in span['exact_span'] and
               f'[S1] Exact excerpt: {QUOTE}' in span['exact_span'] for span in paired)
    assert any(f'[S2] {ASSERTION}' in span['exact_span'] and
               '[S2] Source record: company: Example Labs' in span['exact_span'] and
               'status: unknown' in span['exact_span'] for span in paired)
    assert all(span['exact_span'] in sections[span['section_index']][1] for span in spans)
    assert all('https://' not in span['exact_span'] for span in spans)


def test_reader_v2_fresh_review_binds_extraction_marker_and_old_request_replays(
        tmp_path, monkeypatch):
    result, attempts, _ = accepted_v2()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    monkeypatch.setattr(stage, 'validate_material_checkpoint', lambda job, memo, material: material)
    monkeypatch.setattr(stage, '_installed_digest', lambda name: 'synthetic-model-digest')
    memo = {'source_hash': 'source', 'sections': sections, 'section_projection': 'reader_v2'}
    material = {'memo_digest': 'memo', 'decks': {
        deck: {'sections': rows} for deck, rows in request(sections)['decks'].items()}}
    fresh = stage._review_request({'input_revision': 'synthetic'}, memo, material, tmp_path)
    assert fresh['memo_section_projection'] == 'reader_v2'
    assert fresh['evidence_extraction'] == 'reader_v2_claim_pair_v1'
    assert fresh['digest'] == digest({k: v for k, v in fresh.items() if k != 'digest'})
    assert all(choice['memo_evidence_indices'] for choice in
               compact_review_payload(fresh)['sentence_choices'])
    # A request already saved before the marker was introduced retains its
    # exact digest and extraction behavior on replay.
    earlier = {k: v for k, v in fresh.items() if k not in (
        'memo_section_projection', 'evidence_extraction', 'digest')}
    earlier['digest'] = digest(earlier)
    (tmp_path / 'material_review_request.json').write_text(json.dumps(earlier))
    assert stage._review_request({'input_revision': 'synthetic'}, memo, material,
                                 tmp_path) == earlier
