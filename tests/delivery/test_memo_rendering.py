"""The editable memo and its PDF keep the same recorded section text."""

from io import BytesIO
import re

from docx import Document
from pypdf import PdfReader

from delivery.inspection import inspect_export_pair
from delivery.rendering import render_memo, render_memo_pdf


def test_memo_pair_preserves_long_model_prose_excerpts_and_sources():
    body = (
        'The local model reports an unresolved funding status [S1]. ' * 10
        + '\n\nSource claims and exact excerpts:\n'
        + '[S1] Exact excerpt: {"status":"unknown","amount":"INR 20 crore"}.\n' * 8
    )
    sources = '[S1] https://example.invalid/record | version synthetic-v1\n' * 8
    sections = [(f'Funding reconciliation {index}', body, sources)
                for index in range(1, 4)]
    docx = render_memo('Synthetic company', sections)
    pdf = render_memo_pdf('Synthetic company', sections)
    pair = inspect_export_pair(docx, 'docx', pdf)
    assert pair['pair_status'] == pair['editable_text_status'] == 'pass'
    document = Document(BytesIO(docx))
    editable = '\n'.join(paragraph.text for paragraph in document.paragraphs)
    pages = PdfReader(BytesIO(pdf)).pages
    printed = '\n'.join(page.extract_text() for page in pages)
    for value in ('Funding reconciliation 1', 'Source claims and exact excerpts:',
                  '"status":"unknown"', 'synthetic-v1'):
        assert value in editable
        assert value in printed
    normalize = lambda value: re.sub(r'\s+', ' ', value).strip()
    for heading, model_body, model_sources in sections:
        assert heading in editable
        for line in (*model_body.splitlines(), *model_sources.splitlines()):
            if line.strip():
                assert normalize(line) in normalize(editable)
    assert len(pages) >= 2
    assert all('DRAFT' in page.extract_text() and 'Page ' in page.extract_text()
               for page in pages)


def test_memo_pair_preserves_plain_sections_without_evidence_marker():
    sections = [('Decision', 'The model asks for primary dated records [S1].',
                 '[S1] https://example.invalid/source | version v1')]
    pair = inspect_export_pair(render_memo('Synthetic company', sections), 'docx',
                               render_memo_pdf('Synthetic company', sections))
    assert pair['pair_status'] == pair['editable_text_status'] == 'pass'


def _dense_sections(count=4):
    body = ('The local model reports an unresolved funding status and asks for dated records [S1]. ' * 6
            + '\n\nSource claims and exact excerpts:\n'
            + '[S1] Exact excerpt: {"status":"unknown","amount":"INR 20 crore"}.\n' * 5)
    sources = '[S1] https://example.invalid/record | version synthetic-v1\n' * 4
    return [(f'Funding reconciliation {index}', body, sources) for index in range(1, count + 1)]


def test_editable_memo_uses_the_pdf_page_and_readable_set_off_evidence():
    from docx.oxml.ns import qn
    from delivery.rendering import _MEMO
    sections = _dense_sections()
    document = Document(BytesIO(render_memo('Synthetic company', sections)))
    pdf = PdfReader(BytesIO(render_memo_pdf('Synthetic company', sections)))
    page = document.sections[0]
    # One sheet and one set of margins for both files.
    box = pdf.pages[0].mediabox
    assert (round(page.page_width.mm), round(page.page_height.mm)) == (210, 297)
    assert (round(float(box.width) / 72 * 25.4), round(float(box.height) / 72 * 25.4)) == (210, 297)
    assert [round(value.mm) for value in (page.left_margin, page.right_margin, page.top_margin,
                                          page.bottom_margin)] == [20, 20, 25, 22]
    styles = document.styles
    size = lambda name: styles[name].font.size.pt
    assert (size('Normal'), size('Memo Evidence'), size('Memo Sources')) == (
        _MEMO['body'], _MEMO['evidence'], _MEMO['sources']) == (11, 9.5, 9)
    assert styles['Normal'].paragraph_format.widow_control is True
    # Excerpts sit behind a left rule and an indent; each section opens with a hairline.
    rule = lambda name, side: styles[name].element.pPr.find(qn('w:pBdr')).find(qn(f'w:{side}'))
    assert rule('Memo Evidence', 'left') is not None and rule('Heading 1', 'top') is not None
    assert styles['Memo Evidence'].paragraph_format.left_indent.mm > 3
    # Pagination controls: a heading or label never ends a page; an excerpt is not split.
    assert styles['Heading 1'].paragraph_format.keep_with_next
    assert styles['Memo Label'].paragraph_format.keep_with_next
    assert styles['Memo Evidence'].paragraph_format.keep_together
    by_style = {}
    for paragraph in document.paragraphs:
        by_style.setdefault(paragraph.style.name, []).append(paragraph.text)
    assert len(by_style['Memo Evidence']) == 20 and len(by_style['Memo Sources']) == 16
    # The PDF text sizes match the editable styles.
    sizes = set()
    pdf.pages[0].extract_text(visitor_text=lambda text, cm, tm, font, size_: sizes.add(
        round(size_ * tm[0], 1)) if text.strip() else None)
    assert {11, 9.5, 9, 13.5, 21} <= sizes and min(sizes) >= 8


def test_memo_pdf_never_strands_a_heading_or_label_at_the_foot_of_a_page():
    labels = ('Source claims and exact excerpts:', 'Source versions')
    for count in range(2, 9):
        sections = _dense_sections(count)
        docx, pdf = render_memo('Synthetic company', sections), render_memo_pdf('Synthetic company', sections)
        assert inspect_export_pair(docx, 'docx', pdf)['pair_status'] == 'pass'
        for page in PdfReader(BytesIO(pdf)).pages:
            lines = [line.strip() for line in page.extract_text().splitlines() if line.strip()]
            content = [line for line in lines if not line.startswith(
                ('DRAFT', 'INVESTMENT MEMORANDUM DRAFT', 'Page '))]
            assert content and content[-1] not in labels
            assert not content[-1].startswith('Funding reconciliation')


def test_reader_source_names_get_matching_editable_and_pdf_labels():
    sections = [('Synthetic section', 'Synthetic source-reported point [S1].',
                 '[S1] Synthetic official record')]
    docx = render_memo('Synthetic company', sections)
    pdf = render_memo_pdf('Synthetic company', sections)
    assert 'Sources cited' in PdfReader(BytesIO(pdf)).pages[0].extract_text()
    assert 'Sources cited' in '\n'.join(p.text for p in Document(BytesIO(docx)).paragraphs)
    assert inspect_export_pair(docx, 'docx', pdf)['pair_status'] == 'pass'
