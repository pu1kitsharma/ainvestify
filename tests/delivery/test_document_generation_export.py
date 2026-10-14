"""Exact exported-byte binding cannot promote unreviewed material to approval."""
from copy import deepcopy
import hashlib

import pytest

from agents.inference.model_authorship import digest
from agents.research.document_generation import GenerationError
from delivery.document_generation_export import freeze_draft_export


def args():
    raw = '{"pages": []}'
    return {'inventory_revision': 'a' * 64, 'kind': 'pitch_deck',
        'plan_response': {'id': 'response_1', 'raw_response': raw, 'response_hash': digest(raw)},
        'page_receipts': [{'page_id': 'P1', 'author_response_id': 'response_2',
                           'author_response_hash': 'b' * 64}],
        'renderer_sections': [('Recorded heading', 'Recorded model text', '[S1]', 'evidence')],
        'artifacts': [{'format': 'pptx', 'content': b'actual editable bytes'},
                      {'format': 'pdf', 'content': b'actual PDF bytes'}]}


def test_export_receipt_binds_actual_bytes_and_never_claims_approval():
    value = args()
    original = deepcopy(value)
    result = freeze_draft_export(**value)
    assert value == original
    assert result['files'][0]['sha256'] == hashlib.sha256(b'actual PDF bytes').hexdigest()
    assert result['content_review'] == 'not_run_or_partial' and result['release_status'] == 'draft_only'
    assert result['investor_approval'] == result['financial_validation'] == result['regulatory_approval'] == 'not_established'
    value['artifacts'].reverse()
    assert result == freeze_draft_export(**value)


@pytest.mark.parametrize('mutation', ['raw', 'formats', 'duplicate', 'missing_review', 'missing_page'])
def test_missing_or_altered_receipts_reject(mutation):
    value = args()
    if mutation == 'raw':
        value['plan_response']['raw_response'] += ' modified'
    elif mutation == 'formats':
        value['artifacts'][0]['format'] = 'docx'
    elif mutation == 'duplicate':
        value['page_receipts'][0]['author_response_id'] = 'response_1'
    elif mutation == 'missing_review':
        value['page_receipts'][0]['review_response_id'] = 'response_3'
    else:
        value['page_receipts'] = []
    with pytest.raises(GenerationError):
        freeze_draft_export(**value)
