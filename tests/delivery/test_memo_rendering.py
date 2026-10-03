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
