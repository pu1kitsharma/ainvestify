"""Bounded draft templates. Text is supplied by recorded model projections."""
from __future__ import annotations
from io import BytesIO
import re


def _pdf_font():
    """Embed a Unicode font when the qualified macOS runtime supplies one."""
    from pathlib import Path
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    name = 'RoomDejaVuSans'
    path = Path('/Applications/LibreOffice.app/Contents/Resources/fonts/truetype/DejaVuSans.ttf')
    if not path.is_file():
        name = 'RoomArialUnicode'
        path = Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    if path.is_file():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path)))
        return name
    return 'Helvetica'


def _checked_sections(sections):
    if not sections or len(sections) > 30:
        raise ValueError("Supported draft requires 1–30 sections")
    for section in sections:
        if len(section) not in (3, 4):
            raise ValueError('Draft section shape is unsupported')
        heading, body, sources = section[:3]
        if any(len(item) > limit for item, limit in (
                (heading, 100), (body, 1200), (sources, 1200))):
            raise ValueError("Draft section exceeds supported layout; split it before rendering")
        if len(section) == 4 and section[3] not in {
                'statement', 'evidence', 'comparison', 'timeline'}:
            raise ValueError('Draft slide layout is unsupported')
    return sections


_SENTENCE_END = re.compile(r'(?<=[.!?])["\')\]]*\s+(?=["\'(\[]?[A-Z0-9])')


def _sentences(body):
    """The model's sentences, or the whole body when it is not cleanly two to four.

    Each returned part is exact text; joined by single spaces they are the body.
    """
    parts = _SENTENCE_END.split(body)
    if 2 <= len(parts) <= 4 and ' '.join(parts) == body and all(len(part) >= 20 for part in parts):
        return parts
    return [body]


def _comparison_parts(body):
    """Two columns only where the model wrote two sentences.

    The cut is the sentence end nearest the middle. A colon, a semicolon or a
    space is never a cut: one continuous sentence stays in one column.
    """
    midpoint = len(body) // 2
    candidates = [match.end() for match in _SENTENCE_END.finditer(body)]
    cut = min(candidates, key=lambda value: abs(value-midpoint)) if candidates else -1
    if cut < 20 or cut > len(body)-20:
        return body, ''
    return body[:cut].rstrip(), body[cut:].lstrip()


def _effective_slide_layout(layout, body):
    """A comparison needs two complete sentences; otherwise use a statement panel."""
    if layout == 'comparison' and not _comparison_parts(body)[1]:
        return 'statement'
    return layout


_LEADING = 1.27                         # line pitch, shared by the PPTX and its PDF
# Largest that fits. A one- or two-sentence claim is set as display type; a full
# slide ends at the 12pt floor.
_BODY_SIZES = (40, 34, 30, 26, 22, 19, 16, 14, 12)
_SOURCE_SIZES = (12, 11, 10, 9, 8)      # 8 only when a long list fits no other way
_HEADING_SIZES = (27, 24, 21, 18)
_TOP, _BOTTOM = 2.08, 6.78              # the content band between the two hairlines


def _estimated_lines(text, size, width):
    """A deliberately generous line count for wrapped text; no font file is read,
    so the editable slide and its PDF get the same geometry on every machine.

    Words are wrapped greedily with rough advance widths, so a few long words
    in a narrow column are counted as the lines they really take.
    """
    def ems(word):
        # Capitals, digits and m/w are wider than other lowercase; points are narrow.
        return sum(1.0 if char in 'WMmw@%' else .74 if char.isupper() else .66 if char.isdigit()
                   else .36 if char in ".,;:!'|ijl()[]" else .6 for char in word)
    room = width * 72 / (size * 1.04)               # ems per line, with a safety margin
    lines = 0
    for part in text.splitlines() or ['']:
        used, lines = 0.0, lines + 1
        for word in part.split():
            need = ems(word)
            if used and used + .34 + need > room:
                lines, used = lines + 1, 0.0
            if need > room:                          # a word longer than the line is broken
                lines += int(need // room)
                need %= room
            used += (.34 if used else 0) + need
    return lines


def _estimated_height(text, size, width):
    return _estimated_lines(text, size, width) * size * _LEADING / 72


def _fit_size(text, width, height, sizes):
    """The largest listed size whose estimated text fits the box; else the smallest."""
    for size in sizes:
        if _estimated_height(text, size, width) <= height:
            return size
    return sizes[-1]


def _centred(x, y, w, h, text, size, color):
    """Lower a short text block towards the middle of its panel.

    A sparse slide otherwise leaves its few lines pinned to the top of an
    empty panel. The box keeps its bottom edge, so nothing can overflow.
    """
    used = _estimated_height(text, size, w)
    drop = round(min((h - used) / 2, h * .3), 2) if used < h * .6 else 0
    return (x, round(y + drop, 2), w, round(h - drop, 2), text, size, color)


def _notes_strip(sources, body_need):
    """Source notes along the bottom: as tall as their text needs at a legible size,
    but never past what the body needs at its floor size.

    Returns (label box, notes box, y of the top of the strip).
    """
    cap = max(.67, min(2.4, _BOTTOM - _TOP - .85 - body_need * 1.08))
    size = _fit_size(sources, 11.5, cap, _SOURCE_SIZES)
    height = round(min(cap, max(.34, _estimated_height(sources, size, 11.5) + .06)), 2)
    y = round(_BOTTOM - height, 2)
    return ((.91,round(y - .33, 2),11.5,.25,'SOURCE NOTES',9,'3B6870'),
            (.91,y,11.5,height,sources,size,'42566A'), round(y - .47, 2))


def _hero(body, sources, index):
    """A single short sentence: display type in a full-width panel, alternately dark
    and light through the deck so consecutive statements do not look alike."""
    label, notes, top = _notes_strip(sources, _estimated_height(body, _BODY_SIZES[-1], 10.6))
    y, dark = _TOP + .12, index % 2 == 0
    h = round(top - .2 - y, 2)
    size = _fit_size(body, 10.6, h - .6, _BODY_SIZES)
    drop = round(max(.3, (h - _estimated_height(body, size, 10.6)) / 2), 2)
    shapes = [(.78, y, 11.77, h, '17324D' if dark else 'EAF2F2'),
              (.78, y, .09, h, 'EA5A5C' if dark else '4B8790')]
    return shapes, [(1.35, round(y + drop, 2), 10.6, round(h - drop, 2), body, size,
                     'FFFFFF' if dark else '17324D'), label, notes]


def _points(parts, sources):
    """Several sentences of evidence: one editable row each, with a marker and a
    hairline between rows, above a tinted source strip. None when they do not fit."""
    x, w, gap = 1.3, 10.9, .3 if len(parts) <= 2 else .22
    need = lambda size: sum(_estimated_height(part, size, w) for part in parts) + gap * (len(parts) - 1)
    label, notes, top = _notes_strip(sources, need(_BODY_SIZES[-1]))
    y, bottom = _TOP + .22, top - .25
    size = next((size for size in _BODY_SIZES if size <= 30 and need(size) <= bottom - y), None)
    if size is None:
        return None
    line = size * _LEADING / 72
    y = round(y + min((bottom - y - need(size)) / 2, (bottom - y) * .25), 2)
    shapes = [(.78, round(top - .08, 2), 11.77, round(_BOTTOM + .06 - top + .08, 2), 'EAF2F2'),
              (.78, round(top - .08, 2), .055, round(_BOTTOM + .06 - top + .08, 2), '4B8790')]
    boxes = []
    for index, part in enumerate(parts):
        height = _estimated_height(part, size, w)
        if index:
            shapes.append((x, round(y - gap / 2, 2), w, .012, 'DCE5E9'))
        shapes.append((.86, round(y + (line - .14) / 2, 2), .14, .14, 'EA5A5C'))
        boxes.append((x, y, w, round(height + .06, 2), part, size, '202E3B'))
        y = round(y + height + gap, 2)
    return shapes, boxes + [(1.0, *label[1:]), (1.0, notes[1], 11.4, *notes[3:])]


def _steps(parts, sources):
    """A model-selected timeline of several sentences: one column per sentence, in
    the model's order, hung from a rule with a marker each. None when too long."""
    gap = .4
    w = round((11.5 - gap * (len(parts) - 1)) / len(parts), 2)
    longest = max(parts, key=len)
    label, notes, top = _notes_strip(sources, _estimated_height(longest, _BODY_SIZES[-1], w))
    rule, bottom = _TOP + .42, top - .2
    y = round(rule + .4, 2)
    if _estimated_height(longest, _BODY_SIZES[-1], w) > bottom - y:
        return None
    size = min(_fit_size(longest, w, bottom - y, _BODY_SIZES), 30)
    shapes = [(.78, top, 11.77, .018, 'DCE5E9'), (.91, rule, 11.5, .03, 'B9CBD1')]
    boxes = []
    for index, part in enumerate(parts):
        x = round(.91 + index * (w + gap), 2)
        shapes.append((x, round(rule - .08, 2), .19, .19, 'EA5A5C' if index % 2 == 0 else '4B8790'))
        boxes.append((x, y, w, round(bottom - y, 2), part, size, '202E3B'))
    return shapes, boxes + [label, notes]


def _slide_plan(heading, body, sources, title, layout, index=0):
    """One geometry for the editable slide and its PDF: (decorative shapes, text boxes).

    The model chooses the layout and writes every word. Within that layout the
    arrangement follows the shape of what it wrote: one short sentence becomes a
    display panel, several sentences of evidence become rows, several sentences
    of a timeline become steps. Source notes take the height their text needs,
    the body takes the rest, and each is set in the largest type that fits.
    Text is placed, never changed; `index` only alternates decoration.
    """
    shapes = [(.0,.0,13.333,.085,'EA5A5C'),
              (.78,1.9,11.77,.025,'DCE5E9'),
              (.78,6.9,11.77,.018,'DCE5E9')]
    boxes = [(.65,.25,11.9,.3,'DRAFT • NOT APPROVED FOR INVESTOR DISTRIBUTION',9,'9B4142'),
             (.78,.93,11.85,.85,heading,_fit_size(heading, 11.85, .85, _HEADING_SIZES),'17324D')]
    footer = (.79,7.06,11.7,.22,title,8,'42566A')
    parts = _sentences(body)
    variant = None
    if layout == 'statement' and len(parts) == 1 and len(body) <= 170 and '\n' not in body:
        variant = _hero(body, sources, index)
    elif layout == 'evidence' and len(parts) > 1:
        variant = _points(parts, sources)
    elif layout == 'timeline' and len(parts) > 1:
        variant = _steps(parts, sources)
    if variant:
        return shapes + variant[0], boxes + variant[1] + [footer]
    if layout == 'evidence':
        # One sentence, or more than rows can hold: body beside a full-height notes panel.
        body_box = (.87, 2.33, 7.1, 4.05)
        notes = (8.5, 2.6, 3.7, 3.72)
        source_box = _centred(*notes, sources, _fit_size(sources, notes[2], notes[3],
                                                         _SOURCE_SIZES), '42566A')
        shapes += [(8.28,2.04,4.19,4.5,'EAF2F2'), (8.28,2.04,.055,4.5,'4B8790')]
        boxes += [_centred(*body_box, body, _fit_size(body, body_box[2], body_box[3], _BODY_SIZES),
                           '202E3B'),
                  (8.5,round(source_box[1]-.43,2),3.75,.35,'SOURCE NOTES',9,'3B6870'),
                  source_box, footer]
        return shapes, boxes
    left, right = _comparison_parts(body) if layout == 'comparison' else (body, '')
    x, w = {'comparison': (.98, 5.04), 'timeline': (1.33, 10.82)}.get(layout, (1.02, 10.93))
    y = _TOP + .2
    longest = max((left, right), key=len)
    label, notes, rule_y = _notes_strip(sources, _estimated_height(longest, _BODY_SIZES[-1], w))
    h = round(rule_y - .18 - y, 2)
    body_size = _fit_size(longest, w, h, _BODY_SIZES)
    shapes.append((.78, rule_y, 11.77, .018, 'DCE5E9'))
    if layout == 'comparison':
        # Both columns drop together so their first lines stay level.
        first = _centred(x, y, w, h, longest, body_size, '202E3B')
        panel = round(rule_y - .12 - _TOP, 2)
        shapes += [(.78,_TOP,5.55,panel,'F0F5F5'), (7.0,_TOP,5.55,panel,'F9F1F0'),
                   (.78,_TOP,5.55,.065,'4B8790'), (7.0,_TOP,5.55,.065,'EA5A5C')]
        boxes += [(x,first[1],w,first[3],left,body_size,'202E3B'),
                  (7.3,first[1],w,first[3],right,body_size,'202E3B')]
    else:
        bar = (.8, .055) if layout == 'timeline' else (.78, .065)
        shapes.append((bar[0], round(y - .1, 2), bar[1], round(h + .16, 2), 'EA5A5C'))
        boxes.append(_centred(x, y, w, h, body, body_size, '202E3B'))
    boxes += [label, notes, footer]
    return shapes, boxes


def _slide_text_boxes(heading, body, sources, title, layout, index=0):
    """Shared text geometry for editable and searchable PDF draft views."""
    return _slide_plan(heading, body, sources, title, layout, index)[1]


def render_intro(title, sections):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    for index, section in enumerate(_checked_sections(sections)):
        heading, body, sources = section[:3]
        layout = _effective_slide_layout(
            section[3] if len(section) == 4 else 'statement', body)
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        shapes, boxes = _slide_plan(heading, body, sources, title, layout, index)
        for x,y,w,h,fill in shapes:
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                           Inches(w), Inches(h))
            shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string(fill)
            shape.line.fill.background()
        for x,y,w,h,text,size,color in boxes:
            box = slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
            box.text_frame.word_wrap = True
            box.text_frame.margin_left = box.text_frame.margin_right = 0
            box.text_frame.margin_top = box.text_frame.margin_bottom = 0
            paragraph = box.text_frame.paragraphs[0]
            paragraph.text = text
            paragraph.font.size = Pt(size)
            paragraph.line_spacing = Pt(round(size * _LEADING, 2))   # the PDF's line pitch
            paragraph.font.name = "DejaVu Sans"
            paragraph.font.color.rgb = RGBColor.from_string(color)
    output=BytesIO();deck.save(output);return output.getvalue()


# Point sizes shared by the editable memo and its PDF.
_MEMO = {'title': 21, 'heading': 13.5, 'body': 11, 'evidence': 9.5, 'sources': 9, 'label': 8.5}


def _memo_source_label(sources):
    """Preserve legacy URL/version labels; name reader projection lists plainly."""
    lines = [line.strip() for line in sources.splitlines() if line.strip()]
    if lines and all(re.match(r'^\[S\d+\]\s+[^|]+$', line) for line in lines):
        return 'Sources cited'
    return 'Source versions'


def render_memo(title, sections):
    from docx import Document
    from docx.shared import Mm, Pt
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import RGBColor
    doc=Document()
    # The library's blank template contains a custom bibliography XML part.
    # New drafts do not use it; omit it instead of distributing hidden payloads.
    for key,relationship in list(doc.part.rels.items()):
        if relationship.reltype.endswith('/customXml'):
            doc.part.drop_rel(key)
    page = doc.sections[0]
    # The same sheet and margins as the PDF, so the two paginate alike.
    page.page_width, page.page_height = Mm(210), Mm(297)
    page.top_margin, page.bottom_margin = Mm(25), Mm(22)
    page.left_margin = page.right_margin = Mm(20)
    normal = doc.styles['Normal']
    normal.font.name, normal.font.size = 'DejaVu Sans', Pt(_MEMO['body'])
    normal.paragraph_format.line_spacing = 1.28
    normal.paragraph_format.space_after = Pt(9)
    normal.paragraph_format.widow_control = True

    def edge(style, side, color, width, space):
        """A rule on one side of every paragraph in a style: layout only."""
        properties = style.element.get_or_add_pPr()
        borders = properties.find(qn('w:pBdr'))
        if borders is None:
            borders = OxmlElement('w:pBdr')
            properties.append(borders)
        rule = OxmlElement(f'w:{side}')
        for key, value in (('val', 'single'), ('sz', str(width)), ('space', str(space)),
                           ('color', color)):
            rule.set(qn(f'w:{key}'), value)
        borders.append(rule)
    title_style = doc.styles['Title']
    title_style.font.name, title_style.font.size = 'DejaVu Sans', Pt(_MEMO['title'])
    title_style.font.color.rgb = RGBColor(23, 50, 77)
    title_style.paragraph_format.space_after = Pt(17)
    heading_style = doc.styles['Heading 1']
    heading_style.font.name, heading_style.font.size = 'DejaVu Sans', Pt(_MEMO['heading'])
    heading_style.font.color.rgb = RGBColor(23, 50, 77)
    heading_style.paragraph_format.space_before = Pt(20)
    heading_style.paragraph_format.space_after = Pt(8)
    heading_style.paragraph_format.keep_with_next = True
    edge(heading_style, 'top', 'DCE5E9', 6, 8)          # a hairline opens each section
    for name, size, color, before, after in (
            ('Memo Evidence', _MEMO['evidence'], RGBColor(38, 54, 69), 0, 6),
            ('Memo Sources', _MEMO['sources'], RGBColor(66, 86, 106), 0, 5),
            ('Memo Label', _MEMO['label'], RGBColor(23, 50, 77), 12, 5)):
        style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = normal
        style.font.name, style.font.size, style.font.color.rgb = 'DejaVu Sans', Pt(size), color
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_together = True
    doc.styles['Memo Label'].font.bold = True
    doc.styles['Memo Label'].paragraph_format.keep_with_next = True
    # Excerpts and source versions are set off from the prose, not shrunk below it.
    for name in ('Memo Evidence', 'Memo Sources'):
        doc.styles[name].paragraph_format.left_indent = Mm(4)
        doc.styles[name].paragraph_format.line_spacing = 1.2
    edge(doc.styles['Memo Evidence'], 'left', '4B8790', 12, 6)
    header = page.header.paragraphs[0]
    header.text = "DRAFT — NOT APPROVED FOR INVESTOR DISTRIBUTION"
    header.style = doc.styles['Memo Sources']
    doc.add_paragraph(title, style='Title')
    marker = "\n\nSource claims and exact excerpts:\n"
    for section in _checked_sections(sections):
        heading, body, sources = section[:3]
        doc.add_heading(heading, 1)
        prose, separator, evidence = body.partition(marker)
        for block in prose.split('\n\n'):
            if block:
                doc.add_paragraph(block)
        if separator:
            # Keep the model's marker verbatim; only its presentation changes.
            doc.add_paragraph('Source claims and exact excerpts:', style='Memo Label')
            for line in evidence.splitlines():
                if line:
                    doc.add_paragraph(line, style='Memo Evidence')
        if sources:
            doc.add_paragraph(_memo_source_label(sources), style='Memo Label')
            for line in sources.splitlines():
                if line:
                    doc.add_paragraph(line, style='Memo Sources')
    footer = page.footer.paragraphs[0]
    footer.text = 'INVESTMENT MEMORANDUM DRAFT'
    footer.style = doc.styles['Memo Sources']
    output=BytesIO();doc.save(output);return output.getvalue()


def render_deck_pdf(title, sections):
    """A searchable PDF of the same model-authored slide text.

    This text-preserving export is a draft. The separate pair inspector checks
    exact text and page count; visual parity still needs its own review.
    """
    from reportlab.lib import colors
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    output = BytesIO()
    font = _pdf_font()
    width, height = 13.333 * 72, 7.5 * 72
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=0)
    pdf.setTitle(f"{title} - draft deck")
    for index, section in enumerate(_checked_sections(sections)):
        heading, body, sources = section[:3]
        layout = _effective_slide_layout(
            section[3] if len(section) == 4 else 'statement', body)
        pdf.setFillColor(colors.white)
        pdf.rect(0, 0, width, height, fill=1, stroke=0)
        shapes, boxes = _slide_plan(heading, body, sources, title, layout, index)
        for x,y,w,h,fill in shapes:
            pdf.setFillColor(colors.HexColor('#' + fill))
            pdf.rect(x*72, height-(y+h)*72, w*72, h*72, fill=1, stroke=0)
        for x,y,w,h,value,size,color in boxes:
            if not value:
                continue
            lines = [line for part in value.splitlines() or [""]
                     for line in (simpleSplit(part, font, size, w*72) or [""])]
            leading = size * _LEADING
            if len(lines) * leading > h*72 + 4:
                raise ValueError('Deck PDF text exceeds its matching editable box')
            pdf.setFont(font, size)
            pdf.setFillColor(colors.HexColor('#' + color))
            baseline = height - y*72 - size
            for line in lines:
                pdf.drawString(x*72, baseline, line)
                baseline -= leading
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def render_memo_pdf(title, sections):
    """Searchable PDF using the exact model-authored DOCX fields."""
    from html import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, KeepTogether,
                                    HRFlowable, Table, TableStyle)

    output = BytesIO()
    font = _pdf_font()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=20*mm,
        rightMargin=20*mm, topMargin=25*mm, bottomMargin=22*mm,
        title=f"{title} - draft investment memorandum")
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("MemoTitle", parent=base["Title"],
            fontName=font, fontSize=_MEMO['title'], leading=27,
            textColor=colors.HexColor("#17324D"), alignment=0, spaceAfter=10*mm),
        "heading": ParagraphStyle("MemoHeading", parent=base["Heading2"],
            fontName=font, fontSize=_MEMO['heading'], leading=18.5,
            textColor=colors.HexColor("#17324D"), spaceBefore=2.5*mm, spaceAfter=3*mm,
            keepWithNext=1),
        "body": ParagraphStyle("MemoBody", parent=base["BodyText"],
            fontName=font, fontSize=_MEMO['body'], leading=16.5, spaceAfter=3.2*mm,
            allowWidows=0, allowOrphans=0),
        "label": ParagraphStyle("MemoLabel", parent=base["BodyText"],
            fontName=font, fontSize=_MEMO['label'], leading=12,
            textColor=colors.HexColor("#17324D"), spaceBefore=3.5*mm, spaceAfter=1.8*mm,
            keepWithNext=1),
        "evidence": ParagraphStyle("MemoEvidence", parent=base["BodyText"],
            fontName=font, fontSize=_MEMO['evidence'], leading=13.6,
            textColor=colors.HexColor("#263645"), spaceAfter=0, splitLongWords=1,
            allowWidows=0, allowOrphans=0),
        "sources": ParagraphStyle("MemoSources", parent=base["BodyText"],
            fontName=font, fontSize=_MEMO['sources'], leading=13,
            textColor=colors.HexColor("#42566A"), leftIndent=4*mm, spaceAfter=1.8*mm,
            splitLongWords=1, allowWidows=0, allowOrphans=0),
    }

    def excerpt(line):
        """One excerpt behind the same left rule the editable memo draws. It splits
        across pages only between lines, like any paragraph."""
        panel = Table([[Paragraph(escape(line), styles['evidence'])]],
                      colWidths=[document.width - 1.5*mm], hAlign='RIGHT')
        panel.setStyle(TableStyle([
            ('LINEBEFORE', (0, 0), (0, -1), 1.5, colors.HexColor('#4B8790')),
            ('LEFTPADDING', (0, 0), (-1, -1), 2.5*mm), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
        return [panel, Spacer(1, 2.2*mm)]

    def kept(label, flows):
        """A label never ends a page: it stays with the first item beneath it."""
        return [KeepTogether([label, *flows[0]])] + [item for flow in flows[1:] for item in flow]

    story = [Paragraph(escape(title), styles["title"])]
    marker = "\n\nSource claims and exact excerpts:\n"
    for section in _checked_sections(sections):
        heading, body, sources = section[:3]
        prose, separator, evidence = body.partition(marker)
        blocks = [Paragraph(escape(block).replace('\n', '<br/>'), styles['body'])
                  for block in prose.split('\n\n') if block]
        # A hairline opens each section, as in the editable memo.
        heading_flow = [Spacer(1, 4*mm),
                        HRFlowable(width='100%', thickness=.5, color=colors.HexColor('#DCE5E9'),
                                   spaceBefore=0, spaceAfter=0),
                        Paragraph(escape(heading), styles['heading'])]
        story.append(KeepTogether(heading_flow + ([blocks.pop(0)] if blocks else [])))
        story.extend(blocks)
        lines = [line for line in evidence.splitlines() if line] if separator else []
        if separator:
            label = Paragraph('Source claims and exact excerpts:', styles['label'])
            story.extend(kept(label, [excerpt(line) for line in lines]) if lines else [label])
        versions = [line for line in sources.splitlines() if line]
        if versions:
            story.extend(kept(Paragraph(_memo_source_label(sources), styles['label']),
                              [[Paragraph(escape(line), styles['sources'])] for line in versions]))

    def frame(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#42566A'))
        canvas.drawString(20*mm, height-15*mm, 'DRAFT — NOT APPROVED FOR INVESTOR DISTRIBUTION')
        canvas.drawString(20*mm, 12*mm, 'INVESTMENT MEMORANDUM DRAFT')
        canvas.drawRightString(width-20*mm, 12*mm, f'Page {doc.page}')
        canvas.restoreState()

    document.build(story, onFirstPage=frame, onLaterPages=frame)
    return output.getvalue()


def render_research_pdf(title, sections, *, provenance=""):
    """Render recorded model prose and exact evidence as a readable private draft."""
    from html import escape
    from datetime import date
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether, Table, TableStyle

    if not sections or len(sections) > 30:
        raise ValueError("Supported draft requires 1-30 recorded sections")
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=19*mm,
        rightMargin=19*mm, topMargin=23*mm, bottomMargin=20*mm,
        title=f"{title} - draft research", author="Local deal room")
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("ResearchTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=21, leading=26, textColor=colors.HexColor("#17324D"), alignment=TA_LEFT,
            spaceAfter=5),
        "notice": ParagraphStyle("DraftNotice", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=11, textColor=colors.HexColor("#8B3A3A"), spaceAfter=12),
        "heading": ParagraphStyle("ResearchHeading", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=16, textColor=colors.HexColor("#17324D"), spaceBefore=14,
            spaceAfter=5),
        "body": ParagraphStyle("ResearchBody", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=15, spaceAfter=8),
        "evidence_label": ParagraphStyle("ResearchEvidenceLabel", parent=base["BodyText"],
            fontName="Helvetica-Bold", fontSize=8, leading=11,
            textColor=colors.HexColor("#17324D"), spaceBefore=5, spaceAfter=5),
        "evidence": ParagraphStyle("ResearchEvidence", parent=base["BodyText"],
            fontName="Helvetica", fontSize=8.5, leading=12,
            textColor=colors.HexColor("#263645"), splitLongWords=1),
        "sources": ParagraphStyle("ResearchSources", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.5, leading=11, textColor=colors.HexColor("#42566A"),
            splitLongWords=1, spaceAfter=8),
    }
    story = [Paragraph(escape(title), styles["title"]),
             Paragraph("INVESTMENT RESEARCH DRAFT  |  " + date.today().isoformat(), styles["sources"]),
             Paragraph("DRAFT - source-reported evidence; investment decision and financials unverified", styles["notice"])]
    if provenance:
        story.append(Paragraph(escape(provenance), styles["sources"]))
    marker = "\n\nSource claims and exact excerpts:\n"
    for heading, body, sources in sections:
        if any(len(item) > limit for item, limit in ((heading, 100), (body, 1200), (sources, 1200))):
            raise ValueError("Draft section exceeds supported layout")
        section_flow = []
        prose, separator, evidence = body.partition(marker)
        prose_blocks = [part for part in prose.split("\n\n") if part.strip()]
        heading_block = Paragraph(escape(heading), styles["heading"])
        if prose_blocks:
            section_flow.extend([heading_block,
                Paragraph(escape(prose_blocks[0]).replace("\n", "<br/>"), styles["body"])])
            for part in prose_blocks[1:]:
                section_flow.append(Paragraph(escape(part).replace("\n", "<br/>"), styles["body"]))
        else:
            section_flow.append(heading_block)
        if separator:
            section_flow.append(Paragraph("SOURCE CLAIMS AND EXACT EXCERPTS", styles["evidence_label"]))
            for line in evidence.splitlines():
                if not line.strip():
                    continue
                panel = Table([[Paragraph(escape(line), styles["evidence"])]],
                              colWidths=[document.width])
                panel.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6F9")),
                    ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7E1E8")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                section_flow.extend([panel, Spacer(1, 2*mm)])
        if sources:
            section_flow.append(Paragraph("SOURCE VERSIONS", styles["evidence_label"]))
            section_flow.append(Paragraph(escape(sources).replace("\n", "<br/>"), styles["sources"]))
        section_flow.append(Spacer(1, 3*mm))
        first_panel = next((index for index, flowable in enumerate(section_flow)
                            if isinstance(flowable, Table)), None)
        anchor_count = first_panel + 1 if first_panel is not None else min(2, len(section_flow))
        story.append(KeepTogether(section_flow[:anchor_count]))
        story.extend(section_flow[anchor_count:])

    def page_frame(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor("#D7E1E8"))
        canvas.line(19*mm, height-17*mm, width-19*mm, height-17*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#42566A"))
        canvas.drawString(19*mm, 12*mm, "PRIVATE RESEARCH DRAFT - NOT APPROVED FOR DISTRIBUTION")
        canvas.drawRightString(width-19*mm, 12*mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return output.getvalue()


def qualified_sections(pack):
    """Reconstruct validated model-authored sections; never author replacements."""
    from copy import deepcopy
    from agents.preparation.authored_preparation import validate_authored_pack
    checked=validate_authored_pack(deepcopy(pack))
    facts={f['id']:f for f in checked.get('record',{}).get('facts',[])}
    result=[]
    for key,section in checked.get('sections',{}).items():
        if section.get('status')!='complete':continue
        content=section.get('content',{})
        ids=content.get('fact_ids',[])
        if not ids or any(i not in facts for i in ids):continue
        text='\n\n'.join(value for field,value in content.items() if isinstance(value,str) and field not in {'status'})
        sources='\n'.join(f"[{i}] {facts[i].get('source_url','')}" for i in ids)
        result.append((section.get('title',key),text,sources))
    return result
