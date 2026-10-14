"""Synthetic retrieval stability and scope guard regressions."""
import pytest

from agents.research.rationale_sources import unknown_search_terms, unknown_source_ids


def source(index, passage):
    return {'id': f'S{index}', 'url': f'https://example.test/{index}',
            'title': f'Synthetic record {index}', 'passage': passage,
            'version': f'version-{index}', 'attribution': 'Synthetic fixture'}


def unknown(rationale='Understanding the cash evidence informs the proposed diligence.'):
    return {'question': 'What cash balance and runway are evidenced?',
            'evidence_needed': 'Provide dated cash balances and a cash flow statement.',
            'why_it_matters': rationale}


SOURCES = [source(1, 'The record contains cash balances and dated cash flow statements.'),
           source(2, 'The product roadmap discusses underwriting and insurance products.'),
           source(3, 'The team record lists founders and managers with prior roles.'),
           source(4, 'The financial record reports runway and cash flow balances.')]


def test_repair_text_and_source_input_order_do_not_change_evidence_scope():
    selected = unknown_source_ids(unknown(), SOURCES)
    rewritten = unknown('Underwriting and insurance products are mentioned in this passage.')
    assert unknown_source_ids(rewritten, SOURCES[::-1]) == selected
    assert 'S1' in selected and 'S4' in selected
    assert selected == sorted(selected)


def test_explicit_links_are_retained_before_ranked_passages():
    assert unknown_source_ids(unknown(), SOURCES, ['S3'], max_sources=1) == ['S3']


def test_missing_explicit_link_is_rejected():
    with pytest.raises(ValueError, match='absent source'):
        unknown_source_ids(unknown(), SOURCES, ['S9'])


def test_explicit_links_are_never_silently_truncated():
    with pytest.raises(ValueError, match='more explicit links'):
        unknown_source_ids(unknown(), SOURCES, ['S1', 'S2'], max_sources=1)


def test_duplicate_or_empty_sources_are_rejected():
    for rows in ([], [SOURCES[0], SOURCES[0]]):
        with pytest.raises(ValueError, match='unique complete'):
            unknown_source_ids(unknown(), rows)


def test_serialized_table_delimiters_are_decoded_only_in_versioned_retrieval():
    item = {'question': 'What is operating loss?',
            'evidence_needed': 'Provide dated operating loss records.',
            'why_it_matters': 'The requested records inform operating sustainability.'}
    rows = [source(1, r'["Revenue\noperating\tloss\rrecords"]'),
            source(2, 'This unrelated record lists operating dated summaries.')]
    assert unknown_source_ids(item, rows, max_sources=1) == ['S2']
    assert unknown_source_ids(item, rows, max_sources=1, retrieval_version=2) == ['S1']
    assert rows[0]['passage'] == r'["Revenue\noperating\tloss\rrecords"]'


@pytest.mark.parametrize('version', [0, 3, True, '2'])
def test_unknown_retrieval_version_is_rejected(version):
    with pytest.raises(ValueError, match='retrieval version'):
        unknown_source_ids(unknown(), SOURCES, retrieval_version=version)


def test_inquiry_topics_exclude_function_words_numbers_and_reporting_periods():
    item = {'question': 'What is the cash burn rate given FY22 and Q1-FY23 records?',
            'evidence_needed': 'An audited cash statement showing 2023 balances.',
            'why_it_matters': 'The requested records inform operating sustainability.'}
    terms = unknown_search_terms(item)
    assert {'cash', 'burn', 'rate', 'audited', 'statement'} <= set(terms)
    assert not {'an', 'in', 'is', 'given', 'fy22', 'fy23', 'q1', '2023'} & set(terms)
    assert item['question'] not in terms


@pytest.mark.parametrize('cap', [0, 6, True, 1.5])
def test_invalid_caps_are_rejected(cap):
    with pytest.raises(ValueError, match='source cap'):
        unknown_source_ids(unknown(), SOURCES, max_sources=cap)
