"""Memorandum navigation and summary checks using synthetic reviewed pages."""
import copy
from io import BytesIO

import pytest
from pptx import Presentation

from delivery.deal_documents import deck_render, pages


def page(key, rows=None, **extra):
    return {'key': key, 'title': key.replace('_', ' ').capitalize(), 'brief': '', 'cells': [],
            'takeaways': [], 'exhibits': {'grid': {'header': ['Point', 'Evidence'],
            'rows': rows or [['Supplied point', 'Supplied evidence']]}}, **extra}


def reviewed_pages():
    snapshot = page('snapshot')
    snapshot['exhibits']['kpis'] = [{'label': 'Output', 'value': '120 items', 'sub': 'FY30'}]
    return [snapshot, page('transaction'),
            page('highlights', [['Repeat demand', 'Orders recur under supplied contracts'],
                                ['Delivery capacity', 'A stated process supports fulfilment']]),
            page('risks', [['Counterparty dependence', 'Orders depend on counterparties'],
                           ['Execution', 'Capacity must support delivery']]),
            page('team'), page('segments'), page('trend'),
            page('financials_2', family='financials')]


def specs(built):
    return [pages.page_spec(item, {}) for item in built]


def slide_text(slide):
    text = [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame]
    text += [cell.text for shape in slide.shapes if shape.has_table for row in shape.table.rows for cell in row.cells]
    return '\n'.join(text)


def test_summary_copies_reviewed_evidence_with_final_page_references():
    built = reviewed_pages()
    before = copy.deepcopy(built)
    ordered = pages.memorandum_specs(built, specs(built))
    positions = {spec['heading']: number for number, spec in enumerate(ordered, 3)}
    summary = ordered[0]
    assert summary['heading'] == 'Executive summary'
    assert summary['kpis'] == [{'label': 'Output', 'value': '120 items',
                                'sub': f'FY30 | p. {positions["Snapshot"]}'}]
    assert summary['summary']['highlights']['rows'] == [
        [*row, str(positions['Highlights'])] for row in built[2]['exhibits']['grid']['rows']]
    assert summary['summary']['risks']['rows'] == [
        [row[0], str(positions['Risks'])] for row in built[3]['exhibits']['grid']['rows']]
    assert built == before


def test_contents_point_to_dividers_and_continuations_stay_in_their_section():
    built = reviewed_pages()
    ordered = pages.memorandum_specs(built, specs(built))
    dividers = [(number, spec['heading']) for number, spec in enumerate(ordered, 3) if spec.get('divider')]
    assert [title for _, title in dividers] == ['Company', 'Market', 'Financials', 'Transaction', 'Risks']
    assert ordered[1]['grid']['rows'] == [['Executive summary', '3'], *[[title, str(number)] for number, title in dividers]]
    titles = [spec['heading'] for spec in ordered]
    assert titles.index('Financials') < titles.index('Financials 2') < titles.index('Transaction')
    assert len(ordered) == len(built) + 7


def test_sparse_memorandum_omits_empty_sections_and_keeps_unknown_pages():
    built = [page('transaction'), page('additional_diligence')]
    ordered = pages.memorandum_specs(built, specs(built))
    assert [spec['heading'] for spec in ordered if spec.get('divider')] == ['Company', 'Transaction']
    assert ordered[0]['kpis'] == []
    assert ordered[0]['summary']['highlights']['rows'] == []
    assert ordered[0]['summary']['risks']['rows'] == []
    assert any(spec['heading'] == 'Additional diligence' for spec in ordered)


@pytest.mark.parametrize('heading', ['Investment memorandum', 'Investment memorandum - IN PROGRESS'])
def test_memorandum_renders_summary_contents_and_five_dividers(heading):
    built = reviewed_pages()
    data = pages.render('Synthetic entity', [], built, {'facts': [], 'workbook_cells': []}, 'Draft', heading)
    deck = Presentation(BytesIO(data))
    assert len(deck.slides) == len(built) + 9  # cover, notice, summary, contents, five dividers
    assert 'Important notice' in slide_text(deck.slides[1])
    assert 'Executive summary' in slide_text(deck.slides[2])
    assert 'Contents' in slide_text(deck.slides[3])
    assert '120 items' in slide_text(deck.slides[2])
    assert 'Repeat demand' in slide_text(deck.slides[2])
    assert 'Counterparty dependence' in slide_text(deck.slides[2])
    for slide in deck.slides:
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0
            assert shape.left + shape.width <= deck.slide_width
            assert shape.top + shape.height <= deck.slide_height


def test_missing_summary_inputs_are_requested_without_invented_measures():
    data = pages.render('Synthetic entity', [], [], {'facts': [], 'workbook_cells': []}, 'Draft')
    deck = Presentation(BytesIO(data))
    text = slide_text(deck.slides[2])
    assert len(deck.slides) == 4
    assert 'cited financial measures needed' in text
    assert 'Evidence-backed merits and proofs needed' in text
    assert 'Reviewed risk titles needed' in text
    assert '0 items' not in text


@pytest.mark.parametrize('name,heading', [('pitch_deck', 'Pitch deck'), ('intro_deck', 'Introduction')])
def test_fundraising_decks_keep_their_existing_order_and_page_counts(name, heading):
    built = pages.decks(reviewed_pages())[name]
    data = pages.render('Synthetic entity', [], built, {'facts': [], 'workbook_cells': []}, 'Draft', heading)
    deck = Presentation(BytesIO(data))
    assert len(deck.slides) == len(built) + 2
    for slide, item in zip(list(deck.slides)[2:], built):
        assert item['title'] in slide_text(slide)
    text = '\n'.join(slide_text(slide) for slide in deck.slides)
    assert 'Executive summary' not in text and 'Contents' not in text
    assert not any(spec.get('divider') for spec in specs(built))


def test_dense_summary_and_unbreakable_divider_titles_still_fail_fit_checks():
    built = reviewed_pages()
    built[2]['exhibits']['grid']['rows'] *= 80
    summary = pages.memorandum_specs(built, specs(built))[0]
    with pytest.raises(ValueError, match='grid does not fit'):
        deck_render.trial_page(summary)
    with pytest.raises(ValueError, match='section title does not fit'):
        deck_render.trial_page({'heading': 'X' * 1000, 'divider': True})
