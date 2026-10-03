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


def _comparison_parts(body):
    midpoint = len(body) // 2
    candidates = [match.end() for match in re.finditer(r'[.;:]\s+', body)]
    cut = min(candidates, key=lambda value: abs(value-midpoint)) if candidates else -1
    if cut < 20 or cut > len(body)-20:
        cut = body.rfind(' ', 20, midpoint+1)
    if cut < 20:
        return body, ''
    return body[:cut].rstrip(), body[cut:].lstrip()


def _slide_text_boxes(heading, body, sources, title, layout):
    """Shared geometry for editable and searchable PDF draft views."""
    body_size = 19 if len(body) < 180 else 16 if len(body) < 350 else 12
    source_size = 9 if len(sources) < 250 else 8
    common = [(.65,.25,11.9,.3,'DRAFT • NOT APPROVED FOR INVESTOR DISTRIBUTION',9,'9B4142'),
              (.78,.93,11.85,.85,heading,27,'17324D')]
    if layout == 'evidence':
        common.extend([(.87,2.33,7.1,3.55,body,body_size,'202E3B'),
                       (8.5,2.17,3.75,.35,'SOURCE NOTES',9,'3B6870'),
                       (8.5,2.6,3.7,3.42,sources,source_size,'42566A')])
    elif layout == 'comparison':
        left,right = _comparison_parts(body)
        common.extend([(.98,2.28,5.04,2.93,left,body_size,'202E3B'),
                       (7.3,2.28,5.04,2.93,right,body_size,'202E3B'),
                       (.91,5.62,11.5,.25,'SOURCE NOTES',8,'3B6870'),
                       (.91,5.97,11.5,.67,sources,source_size,'42566A')])
    elif layout == 'timeline':
        common.extend([(1.33,2.2,10.82,3.02,body,body_size,'202E3B'),
                       (.91,5.62,11.5,.25,'SOURCE NOTES',8,'3B6870'),
                       (.91,5.97,11.5,.67,sources,source_size,'42566A')])
    else:
        common.extend([(1.02,2.3,10.93,2.95,body,body_size,'202E3B'),
                       (.91,5.62,11.5,.25,'SOURCE NOTES',8,'3B6870'),
                       (.91,5.97,11.5,.67,sources,source_size,'42566A')])
    common.append((.79,7.06,11.7,.22,title,8,'42566A'))
    return common


def _slide_shapes(layout):
    """Decorative shapes only; model-authored facts stay in text boxes."""
    shapes = [(.0,.0,13.333,.085,'EA5A5C'),
              (.78,1.9,11.77,.025,'DCE5E9'),
              (.78,6.9,11.77,.018,'DCE5E9')]
    if layout == 'evidence':
        shapes += [(8.28,2.04,4.19,4.34,'EAF2F2'),
                   (8.28,2.04,.055,4.34,'4B8790')]
    elif layout == 'comparison':
        shapes += [(.78,2.08,5.55,3.32,'F0F5F5'),
                   (7.0,2.08,5.55,3.32,'F9F1F0'),
                   (.78,2.08,5.55,.065,'4B8790'),
                   (7.0,2.08,5.55,.065,'EA5A5C')]
    elif layout == 'timeline':
        shapes += [(.8,2.16,.055,3.04,'EA5A5C')]
    else:
        shapes += [(.78,2.18,.065,3.1,'EA5A5C'),
                   (.78,5.5,11.77,.018,'DCE5E9')]
    return shapes


def render_intro(title, sections):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    for section in _checked_sections(sections):
        heading, body, sources = section[:3]
        layout = section[3] if len(section) == 4 else 'statement'
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        for x,y,w,h,fill in _slide_shapes(layout):
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                           Inches(w), Inches(h))
            shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string(fill)
            shape.line.fill.background()
        for x,y,w,h,text,size,color in _slide_text_boxes(heading,body,sources,title,layout):
            box = slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
            box.text_frame.word_wrap = True
            box.text_frame.margin_left = box.text_frame.margin_right = 0
            box.text_frame.margin_top = box.text_frame.margin_bottom = 0
            paragraph = box.text_frame.paragraphs[0]
            paragraph.text = text
            paragraph.font.size = Pt(size)
            paragraph.font.name = "DejaVu Sans"
            paragraph.font.color.rgb = RGBColor.from_string(color)
    output=BytesIO();deck.save(output);return output.getvalue()


def render_memo(title, sections):
    from docx import Document
    from docx.shared import Inches, Pt
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import RGBColor
    doc=Document()
    # The library's blank template contains a custom bibliography XML part.
    # New drafts do not use it; omit it instead of distributing hidden payloads.
    for key,relationship in list(doc.part.rels.items()):
        if relationship.reltype.endswith('/customXml'):
            doc.part.drop_rel(key)
    page = doc.sections[0]
    page.top_margin, page.bottom_margin = Inches(.82), Inches(.75)
    page.left_margin = page.right_margin = Inches(.78)
    normal = doc.styles['Normal']
    normal.font.name, normal.font.size = 'DejaVu Sans', Pt(10.5)
    normal.paragraph_format.line_spacing = 1.28
    normal.paragraph_format.space_after = Pt(8)
    title_style = doc.styles['Title']
    title_style.font.name, title_style.font.size = 'DejaVu Sans', Pt(21)
    title_style.font.color.rgb = RGBColor(23, 50, 77)
    title_style.paragraph_format.space_after = Pt(17)
    heading_style = doc.styles['Heading 1']
    heading_style.font.name, heading_style.font.size = 'DejaVu Sans', Pt(13)
    heading_style.font.color.rgb = RGBColor(23, 50, 77)
    heading_style.paragraph_format.space_before = Pt(17)
    heading_style.paragraph_format.space_after = Pt(7)
    heading_style.paragraph_format.keep_with_next = True
    for name, size, color, before, after in (
            ('Memo Evidence', 9, RGBColor(38, 54, 69), 0, 5),
            ('Memo Sources', 8.5, RGBColor(66, 86, 106), 0, 7),
            ('Memo Label', 8, RGBColor(23, 50, 77), 10, 4)):
        style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = normal
        style.font.name, style.font.size, style.font.color.rgb = 'DejaVu Sans', Pt(size), color
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_together = True
    doc.styles['Memo Label'].font.bold = True
    doc.styles['Memo Label'].paragraph_format.keep_with_next = True
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
            doc.add_paragraph('Source versions', style='Memo Label')
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
    for section in _checked_sections(sections):
        heading, body, sources = section[:3]
        layout = section[3] if len(section) == 4 else 'statement'
        pdf.setFillColor(colors.white)
        pdf.rect(0, 0, width, height, fill=1, stroke=0)
        for x,y,w,h,fill in _slide_shapes(layout):
            pdf.setFillColor(colors.HexColor('#' + fill))
            pdf.rect(x*72, height-(y+h)*72, w*72, h*72, fill=1, stroke=0)
        for x,y,w,h,value,size,color in _slide_text_boxes(heading,body,sources,title,layout):
            if not value:
                continue
            lines = [line for part in value.splitlines() or [""]
                     for line in (simpleSplit(part, font, size, w*72) or [""])]
            leading = size * 1.27
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
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether

    output = BytesIO()
    font = _pdf_font()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=20*mm,
        rightMargin=20*mm, topMargin=25*mm, bottomMargin=22*mm,
        title=f"{title} - draft investment memorandum")
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("MemoTitle", parent=base["Title"],
            fontName=font, fontSize=21, leading=27, textColor=colors.HexColor("#17324D"),
            alignment=0, spaceAfter=13*mm),
        "heading": ParagraphStyle("MemoHeading", parent=base["Heading2"],
            fontName=font, fontSize=13, leading=18, textColor=colors.HexColor("#17324D"),
            spaceBefore=6*mm, spaceAfter=2.5*mm, keepWithNext=1),
        "body": ParagraphStyle("MemoBody", parent=base["BodyText"],
            fontName=font, fontSize=10.5, leading=16, spaceAfter=3*mm),
        "label": ParagraphStyle("MemoLabel", parent=base["BodyText"],
            fontName=font, fontSize=8.5, leading=12, textColor=colors.HexColor("#17324D"),
            spaceBefore=2.5*mm, spaceAfter=1.5*mm, keepWithNext=1),
        "evidence": ParagraphStyle("MemoEvidence", parent=base["BodyText"],
            fontName=font, fontSize=9, leading=13, textColor=colors.HexColor("#263645"),
            leftIndent=3*mm, spaceAfter=2.3*mm, splitLongWords=1),
        "sources": ParagraphStyle("MemoSources", parent=base["BodyText"],
            fontName=font, fontSize=8.5, leading=12.5, textColor=colors.HexColor("#42566A"),
            leftIndent=3*mm, spaceAfter=2*mm, splitLongWords=1),
    }
    story = [Paragraph(escape(title), styles["title"])]
    marker = "\n\nSource claims and exact excerpts:\n"
    for section in _checked_sections(sections):
        heading, body, sources = section[:3]
        prose, separator, evidence = body.partition(marker)
        blocks = [Paragraph(escape(block).replace('\n', '<br/>'), styles['body'])
                  for block in prose.split('\n\n') if block]
        heading_flow = Paragraph(escape(heading), styles['heading'])
        if blocks:
            story.append(KeepTogether([heading_flow, blocks.pop(0)]))
        else:
            story.append(heading_flow)
        story.extend(blocks)
        if separator:
            story.append(Paragraph('Source claims and exact excerpts:', styles['label']))
            story.extend(Paragraph(escape(line), styles['evidence'])
                         for line in evidence.splitlines() if line)
        if sources:
            story.append(Paragraph('Source versions', styles['label']))
            story.extend(Paragraph(escape(line), styles['sources'])
                         for line in sources.splitlines() if line)
        story.append(Spacer(1, 2*mm))

    def frame(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setFont(font, 7.5)
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
