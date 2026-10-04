"""Synthetic regressions for complete memo source selection in local materials."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_slides import (
    IntroSourceDeckSpec, StructuredDeckSpec, _evidence_options_v7,
    _source_claim_map_v7, memo_claim_options, memo_claim_map,
    project_source_bound, project_structured,
    replay_material_rows, validate_source_bound_claims,
)
from scripts.private_material_worker import draft_materials


SECTIONS = [
    ['Product and evidence',
     'The company claims a scheduling product for small freight operators [S1]. '
     'The company statement omits audited financials [S1].\n'
     '[S1] The company claims a scheduling product but provides no audited financials. '
     'Exact excerpt: The company describes scheduling software and provides no audited financials.',
     '[S1] https://example.invalid/product | synthetic'],
    ['Funding',
     '[S2] A registry reports a 2025 Seed round with unknown status. Exact excerpt: '
     '{"date":"2025","round":"Seed","status":"unknown"}',
     '[S2] https://example.invalid/funding | synthetic'],
]


def _slide(text, source='S1', purpose='product', heading='Company product'):
    return {'heading': heading, 'sentences': [{'text': text, 'source_id': source}],
            'layout': 'evidence', 'purpose': purpose}


class SourceKeyModel:
    name = 'synthetic-local'
    last_response_text = ''
    last_route = {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        payload = json.loads(evidence)
        assert 'sections' not in payload
        assert set(payload['evidence_by_source']) == {'S1', 'S2'}
        product = _slide('The company claims a scheduling product for small freight operators and lacks independently verified financial results')
        funding = _slide('A registry reports a 2025 Seed round with unknown status and does not establish completion',
                         'S2', 'diligence', 'Funding history')
        financial = _slide('The company statement omits audited financials, so the financial evidence remains incomplete',
                           'S1', 'financial_unknown', 'Financial evidence gap')
        slides = [product, financial] if task.endswith('intro_deck') else [
            product, product, funding, product, financial]
        result = schema.model_validate({'slides': slides})
        self.last_response_text = result.model_dump_json()
        self.last_route = {'model': self.name}
        return result


def test_complete_excerpt_excludes_paginated_json_fragment():
    sections = [
        ['Fragment', '[S3] A registry lists a 2026 round. Exact excerpt: {"company":"Sample", "status":',
         '[S3] https://example.invalid/round | synthetic'],
        ['Complete', '[S3] A registry lists a 2026 round with unknown status. Exact excerpt: '
         '{"company":"Sample","date":"2026","status":"unknown"}',
         '[S3] https://example.invalid/round | synthetic'],
    ]
    chosen = _evidence_options_v7(sections)
    assert len(chosen) == 1
    assert chosen[0]['section_index'] == 1
    assert chosen[0]['quote'].endswith('"status":"unknown"}')


def test_reader_v2_appendix_pairs_model_assertions_with_excerpts_for_drafts():
    from tests.research.test_memo_section_projection import accepted_v2, SOURCES
    from agents.research.investment_memo import renderable_sections
    result, attempts, _ = accepted_v2()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    options = memo_claim_options(sections)
    assert {option['source_id'] for option in options} == {'S1', 'S2'}
    assert any('The source reports a scheduling tool' in option['quote'] and
               'Exact excerpt:' in option['quote'] for option in options)
    assert any('Seed' in option['quote'] and 'status: unknown' in option['quote']
               for option in options)
    assert not any('https://' in option['quote'] for option in options)
    packet = memo_claim_map(sections)
    assert set(packet) == {'S1', 'S2'}


def test_source_packet_keeps_exact_financial_gap_and_binds_one_source():
    packet = _source_claim_map_v7(SECTIONS)
    assert len(packet['S1']) == 2
    assert 'omits audited financials' in packet['S1'][1]
    spec = IntroSourceDeckSpec.model_validate({'slides': [
        _slide('The company claims a scheduling product for small freight operators and needs independent diligence'),
        _slide('A registry reports a 2025 Seed round with unknown status and needs verification',
               'S2', 'diligence', 'Funding history'),
    ]})
    projected = project_source_bound(spec, _evidence_options_v7(SECTIONS))
    assert [slide.sentences[0].source_ids for slide in projected.slides] == [['S1'], ['S2']]
    forged = spec.model_dump()
    forged['slides'][1]['sentences'][0]['source_id'] = 'S1'
    with pytest.raises(ValueError, match='omits sentence numbers or dates'):
        project_source_bound(IntroSourceDeckSpec.model_validate(forged),
                             _evidence_options_v7(SECTIONS))


def test_content_gate_rejects_status_loss_prompt_echo_and_layout_mismatch():
    options = [
        {'source_id': 'S1', 'quote': 'The company claims to build scheduling software without audited financials.'},
        {'source_id': 'S2', 'quote': 'A registry reports a 2025 Seed round; status is unknown.'},
    ]
    def spec(heading, sentence, source='S1', purpose='risk', layout='evidence'):
        slide = {'heading': heading, 'layout': layout, 'purpose': purpose,
                 'sentences': [{'text': sentence, 'source_ids': [source]}]}
        return StructuredDeckSpec.model_validate({'slides': [slide, slide]})
    cases = [
        ('Funding history', 'A registry reports a 2025 Seed round.', 'S2', 'risk', 'evidence', 'status is unknown'),
        ('Financial gap', 'Financial evidence is missing, unknown, unverified, and unavailable.', 'S1', 'risk', 'evidence', 'generic status checklist'),
        ('Investment risk', 'The company claims to build scheduling software.', 'S1', 'risk', 'comparison', 'Comparison slide needs two'),
        ('Market context', 'Audited financial evidence was not supplied.', 'S1', 'risk', 'evidence', 'Market heading does not match'),
        ('Product solution', 'The product is scheduling software for freight operators.', 'S1', 'product', 'evidence', 'loses attribution'),
        ('Market opportunity', 'The company claims freight operators require scheduling software.', 'S1', 'risk', 'evidence', 'lacks source support'),
    ]
    for heading, sentence, source, purpose, layout, error in cases:
        with pytest.raises(ValueError, match=error):
            validate_source_bound_claims(spec(heading, sentence, source, purpose, layout),
                                         options, content_alignment=True)
    assert validate_source_bound_claims(spec('Product solution',
        'The company claims to build scheduling software for freight operators.',
        purpose='product'), options, content_alignment=True)


def test_audited_omission_is_versioned_disclosure_equivalent():
    slide = {'heading': 'Financial evidence gap', 'layout': 'evidence',
             'purpose': 'financial_unknown', 'sentences': [{
                 'text': 'The company statement omits audited financials and needs verification before any investment conclusion',
                 'source_ids': ['S1']}]}
    spec = StructuredDeckSpec.model_validate({'slides': [slide, slide]})
    with pytest.raises(ValueError, match='Financial unknown slide lacks'):
        project_structured(spec, SECTIONS)
    assert 'audited financials' in project_structured(
        spec, SECTIONS, audited_omission=True).slides[0].body


def test_v7_v8_source_keyed_drafts_replay_without_company_prose_in_code(tmp_path):
    for version in ('evidence_v7', 'evidence_v8'):
        root = tmp_path / version
        root.mkdir()
        request = {'input_revision': 'synthetic', 'source_hash': 'hash',
                   'memo_digest': 'memo', 'sections': SECTIONS,
                   'replay_contracts': {'intro_deck': version, 'pitch_deck': version}}
        (root / 'material_request.json').write_text(json.dumps({**request,
            'digest': digest(request)}))
        (root / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
        (root / 'model.json').write_text(json.dumps({'profiles': {'draft': SourceKeyModel.name}}))
        model = SourceKeyModel()
        assert draft_materials(root, model)['state'] == 'needs_resume'
        result = draft_materials(root, model)
        assert result['state'] == 'accepted'
        attempts = json.loads((root / 'material_attempts.json').read_text())
        for kind in ('intro_deck', 'pitch_deck'):
            base = {key: value for key, value in request.items() if key != 'replay_contracts'}
            base['kind'] = kind
            assert replay_material_rows(kind, base, attempts, SECTIONS,
                                        contract_version=version)['state'] == 'accepted'
