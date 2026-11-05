"""The investment memorandum as a Word file: finding, exhibit, then what it means. The PDF is converted from this file."""
from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from delivery.deal_documents.deck_render import to_pdf

FONT = 'Calibri'
NAVY, TEAL, GREY = RGBColor(0x0B, 0x25, 0x45), RGBColor(0x13, 0x80, 0x8C), RGBColor(0x59, 0x63, 0x6E)


def _run(paragraph, text, size, *, bold=False, colour=None, italic=False):
    run = paragraph.add_run(text)
    run.font.name, run.font.size, run.bold, run.italic = FONT, Pt(size), bold, italic
    run._element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
    if colour is not None:
        run.font.color.rgb = colour
    return run


def _space(paragraph, before=0, after=6, line=1.15):
    paragraph.paragraph_format.space_before, paragraph.paragraph_format.space_after = Pt(before), Pt(after)
    paragraph.paragraph_format.line_spacing = line
    return paragraph


def _rule(cell, side):
    borders = cell._tc.get_or_add_tcPr().find(qn('w:tcBorders'))
    if borders is None:
        borders = OxmlElement('w:tcBorders')
        cell._tc.get_or_add_tcPr().append(borders)
    edge = OxmlElement(f'w:{side}')
    for key, value in (('val', 'single'), ('sz', '6'), ('color', '0B2545')):
        edge.set(qn(f'w:{key}'), value)
    borders.append(edge)


def _exhibit(document, number, exhibit):
    _space(document.add_paragraph(), before=8, after=3).add_run()
    title = document.paragraphs[-1]
    title.paragraph_format.keep_with_next = True
    _run(title, f'Exhibit {number}: {exhibit["title"]}', 10, bold=True, colour=TEAL)
    rows = [exhibit['header']] + exhibit['rows']
    table = document.add_table(rows=len(rows), cols=len(exhibit['header']))
    for row_number, row in enumerate(rows):
        for column, value in enumerate(row):
            cell = table.cell(row_number, column)
            paragraph = _space(cell.paragraphs[0], after=1, line=1)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT if column == 0 else WD_ALIGN_PARAGRAPH.RIGHT
            _run(paragraph, str(value), 9, bold=row_number == 0, colour=NAVY if row_number == 0 else None)
            if row_number == 0:
                _rule(cell, 'bottom')
    if exhibit.get('note'):
        _run(_space(document.add_paragraph(), before=2, after=8), exhibit['note'], 8, colour=GREY, italic=True)


def build_docx(company, notices, sections):
    document = Document()
    page = document.sections[0]
    page.left_margin = page.right_margin = Cm(2.3)
    page.top_margin = page.bottom_margin = Cm(2.2)
    _space(document.add_paragraph(), before=150, after=4)
    _run(document.paragraphs[-1], company, 30, bold=True, colour=NAVY)
    _run(_space(document.add_paragraph(), after=4), 'Investment memorandum', 16, colour=TEAL)
    _run(_space(document.add_paragraph(), after=0), 'Draft. Strictly private and confidential.', 11, colour=GREY)
    document.add_page_break()
    for title, text in notices:
        _run(_space(document.add_paragraph(), before=6, after=2), title, 10, bold=True, colour=NAVY)
        _run(_space(document.add_paragraph(), after=4), text, 9, colour=GREY)
    document.add_page_break()
    exhibits = 0
    # An investor reads the summary first, whatever order the sections were written in.
    for section in sorted(sections, key=lambda item: item.get('section') != 'summary'):
        if not section['paragraphs']:
            continue
        heading = _space(document.add_paragraph(), before=16, after=2)
        heading.paragraph_format.keep_with_next = True
        _run(heading, section['title'].upper(), 9, bold=True, colour=TEAL)
        if section.get('headline'):
            finding = _space(document.add_paragraph(), after=6, line=1.05)
            finding.paragraph_format.keep_with_next = True
            _run(finding, section['headline'], 15, bold=True, colour=NAVY)
        for exhibit in section.get('exhibits', []):
            exhibits += 1
            _exhibit(document, exhibits, exhibit)
        for merit in section.get('merits', []):
            line = _space(document.add_paragraph(), after=5, line=1.15)
            _run(line, merit['claim'] + ' ', 11, bold=True, colour=NAVY)
            _run(line, merit['proof'], 11)
        for paragraph in section['paragraphs']:
            _run(_space(document.add_paragraph(), after=7, line=1.2), paragraph['text'], 11)
        if section['state'] != 'valid':
            _run(_space(document.add_paragraph(), after=4), 'This section needs review before use.', 9, colour=GREY, italic=True)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def render(company, notices, sections, fmt):
    docx = build_docx(company, notices, sections)
    return docx if fmt == 'docx' else to_pdf(docx, 'docx')
