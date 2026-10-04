"""Purpose-first local material phases over a reader_v2 synthetic memo."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.investment_memo import renderable_sections
from agents.research.material_purpose_draft import (
    PurposeIntro, PurposePitch, purpose_payload, _slot_evidence_v6, _schema_v7,
)
from agents.research.material_slides import replay_material_rows
from scripts.private_material_worker import draft_materials
from tests.research.test_memo_section_projection import accepted_v2, SOURCES


def _slide(heading, sentence, source='S1', layout='evidence'):
    return {'heading': heading, 'sentences': [{'text': sentence, 'source_id': source}],
            'layout': layout}


COMPANY = _slide('Company and pilot',
    'The source reports a scheduling tool for clinics and a pilot with one clinic, subject to further verification.')
PRODUCT = _slide('Reported product and pilot',
    'The source describes a scheduling tool for clinics and a pilot with one clinic but reports no repeat order.')
FUNDING = _slide('Reported financing',
    'A registry lists a Seed financing entry with unknown status, so the reported round is not confirmed as closed.', 'S2')
RISK = _slide('Evidence risks',
    'The reviewed memo does not establish repeat demand or earned revenue from the single reported pilot.')
FINANCIAL = {'heading': 'Financial evidence gap',
    'financial_status': {'text': 'Financial results remain unverified because the reviewed memo does not establish earned revenue from this pilot.',
                         'source_id': 'S1'},
    'sentences': [], 'layout': 'evidence'}
MARKET = _slide('Market evidence',
    'The reviewed memo does not establish repeat market demand from the single reported pilot.')
DIFFERENTIATION = _slide('Differentiation evidence',
    'The source describes a scheduling tool and one pilot but does not establish repeat use or distinct execution evidence.')


class PurposeModel:
    name = 'synthetic-local'
    last_response_text = ''
    last_route = {}

    def __init__(self, *, weak_financial=False):
        self.weak_financial = weak_financial

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        payload = json.loads(evidence)
        assert payload['funding_required'] is True
        assert set(payload['evidence_by_source']) == {'S1', 'S2'}
        assert 'sections' not in payload
        if task.endswith('intro_deck'):
            answer = {'company': COMPANY, 'product': PRODUCT, 'funding': FUNDING,
                      'risk': RISK, 'financial_unknown': FINANCIAL}
        else:
            answer = {'thesis': COMPANY, 'product': PRODUCT, 'market': MARKET,
                      'differentiation': DIFFERENTIATION, 'funding': FUNDING,
                      'risk': RISK, 'financial_unknown': FINANCIAL}
        if self.weak_financial:
            answer['financial_unknown'] = {**FINANCIAL,
                'financial_status': {'text': 'The source does not establish earned revenue or repeat demand.',
                                     'source_id': 'S1'}}
        result = schema.model_validate(answer)
        self.last_response_text = result.model_dump_json()
        self.last_route = {'model': self.name}
        return result


def _memo_sections():
    result, attempts, _ = accepted_v2()
    return renderable_sections(result, SOURCES, attempts, projection='reader_v2')


def test_reader_v2_packet_sets_required_slots_without_writing_claims():
    sections = _memo_sections()
    payload = purpose_payload('pitch_deck', {'kind': 'pitch_deck',
        'memo_digest': 'synthetic'}, sections)
    assert payload['funding_required'] is True
    assert payload['required_slots'] == [
        'thesis', 'product', 'market', 'differentiation', 'funding', 'risk',
        'financial_unknown']
    assert 'status: unknown' in payload['evidence_by_source']['S2'][0]
    assert any('earned revenue' in item for item in payload['evidence_by_source']['S1'])
    assert payload['financial_unknowns'] == [{
        'question': 'What revenue and cost are attributable to this product?',
        'memo_text': 'The source does not report economic results or margins.\n\nCompany accounts and a scoped recognition policy.'}]
    assert not any('https://' in item for items in payload['evidence_by_source'].values()
                   for item in items)


def test_purpose_schema_has_no_model_chosen_purpose_field():
    valid = {'company': COMPANY, 'product': PRODUCT, 'funding': FUNDING,
             'risk': RISK, 'financial_unknown': FINANCIAL}
    assert PurposeIntro.model_validate(valid).company.heading == 'Company and pilot'
    with pytest.raises(ValueError):
        PurposeIntro.model_validate({**valid, 'company': {**COMPANY, 'purpose': 'financial_unknown'}})


def test_two_purpose_first_calls_replay_and_invalid_response_has_no_retry(tmp_path):
    sections = _memo_sections()
    request = {'input_revision': 'synthetic', 'source_hash': 'hash',
               'memo_digest': 'memo', 'sections': sections,
               'replay_contracts': {'intro_deck': 'purpose_v2',
                                    'pitch_deck': 'purpose_v2'}}
    (tmp_path / 'material_request.json').write_text(json.dumps({**request,
        'digest': digest(request)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    (tmp_path / 'model.json').write_text(json.dumps({
        'profiles': {'draft': PurposeModel.name}}))
    model = PurposeModel()
    assert draft_materials(tmp_path, model)['state'] == 'needs_resume'
    result = draft_materials(tmp_path, model)
    assert result['state'] == 'accepted'
    attempts = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert len(attempts) == 2
    for kind in ('intro_deck', 'pitch_deck'):
        base = {key: value for key, value in request.items() if key != 'replay_contracts'}
        base['kind'] = kind
        replayed = replay_material_rows(kind, base, attempts, sections,
                                        contract_version='purpose_v2')
        assert replayed['state'] == 'accepted'
    tampered = json.loads(json.dumps(attempts))
    tampered[0]['answer']['company']['heading'] = 'Changed manually'
    tampered_state = replay_material_rows('intro_deck', {'kind': 'intro_deck',
        **{key: value for key, value in request.items()
           if key != 'replay_contracts'}}, tampered, sections,
        contract_version='purpose_v2')
    assert tampered_state['state'] == 'blocked'
    assert 'original response' in tampered_state['reason']


def test_purpose_response_cap_is_one_per_deck():
    sections = _memo_sections()
    base = {'kind': 'intro_deck', 'input_revision': 'synthetic',
            'source_hash': 'hash', 'memo_digest': 'memo', 'sections': sections}
    state = replay_material_rows('intro_deck', base, [], sections,
                                 contract_version='purpose_v2')
    assert state['schema'] is PurposeIntro
    assert PurposePitch.model_json_schema()['required']
    with pytest.raises(ValueError, match='one-response cap'):
        replay_material_rows('intro_deck', base,
            [{'task': 'material_intro_deck', 'id': 'a'},
             {'task': 'material_intro_deck', 'id': 'b'}], sections,
            contract_version='purpose_v2')


def test_weak_model_authored_financial_status_blocks_without_retry(tmp_path):
    sections = _memo_sections()
    request = {'input_revision': 'synthetic', 'source_hash': 'hash',
               'memo_digest': 'memo', 'sections': sections,
               'replay_contracts': {'intro_deck': 'purpose_v2',
                                    'pitch_deck': 'purpose_v2'}}
    (tmp_path / 'material_request.json').write_text(json.dumps({**request,
        'digest': digest(request)}))
    (tmp_path / 'material_budget.json').write_text(json.dumps({'seconds': 90}))
    (tmp_path / 'model.json').write_text(json.dumps({
        'profiles': {'draft': PurposeModel.name}}))
    result = draft_materials(tmp_path, PurposeModel(weak_financial=True))
    assert result['state'] == 'blocked'
    attempts = json.loads((tmp_path / 'material_attempts.json').read_text())
    assert len(attempts) == 1
    base = {key: value for key, value in request.items() if key != 'replay_contracts'}
    replayed = replay_material_rows('intro_deck', {**base, 'kind': 'intro_deck'},
                                    attempts, sections, contract_version='purpose_v2')
    assert replayed['state'] == 'blocked'
    assert 'same-sentence disclosure' in replayed['reason']


def test_single_slot_packet_excludes_unrelated_source_and_metadata():
    sections = _memo_sections()
    evidence = purpose_payload('pitch_deck', {'kind': 'pitch_deck'},
                               sections)['evidence_by_source']
    product = _slot_evidence_v6('product', evidence)
    financial = _slot_evidence_v6('financial_unknown', evidence)
    assert set(product) == {'S1'}
    assert set(financial) == {'S1'}
    assert all('Exact excerpt:' not in claim and 'Memo analysis:' not in claim
               for claims in product.values() for claim in claims)
    schema = _schema_v7('product', product)
    with pytest.raises(ValueError):
        schema.model_validate({'heading': 'Product', 'layout': 'statement',
            'sentences': [{'text': 'The source reports a scheduling tool for clinics.',
                           'source_id': 'product.S1'}]})
