"""Investor deck layouts: a PowerPoint built here, and its PDF converted from that same file.

An action title over a body of evidence cards, a native chart or a native table,
with the source as a footnote, on a real cover. Every chart and table stays
editable in PowerPoint. Calibri is on every Windows machine and LibreOffice maps
it to the metric-compatible Carlito, so the PDF keeps the PowerPoint's layout.
Text that would not fit at the smallest size raises ValueError so the slide's
writer can shorten it; nothing is cut off.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_TICK_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt
from reportlab.pdfbase.pdfmetrics import stringWidth

from delivery.deal_documents.semantics import sentences

FONT = 'Calibri'
NAVY, TEAL, CORAL, SLATE = '0B2545', '13808C', 'C8553D', '6B7A90'
INK, MUTED, PANEL, RULE, WHITE = '1F2A37', '5B6878', 'F1F4F8', 'D5DCE5', 'FFFFFF'
SERIES = (NAVY, TEAL, CORAL)
ACCENT = {'risk': CORAL, 'question': SLATE}
WIDTH, HEIGHT, MARGIN = 13.333, 7.5, .6
INNER = WIDTH - 2 * MARGIN
BODY_TOP, BODY_BOTTOM = 1.4, 6.42
TITLE_SIZES, CARD_SIZES, NOTICE_SIZES = (26, 24, 22, 20), (18, 17, 16, 15, 14, 13, 12, 11), (12, 11.5, 11, 10.5, 10)
CHART_WIDTH = 8.1
KPI_HEIGHT = 1.05
FOOTER = 'Strictly private and confidential  |  Draft, not approved for distribution'
CONVERT_TIMEOUT = 180
MIN_TABLE_SIZE = 10


def _colour(value):
    return RGBColor.from_string(value)


def _wrapped(text, size, width, bold=False):
    """Lines the text takes in `width` inches. Helvetica runs a little wider than Calibri, so this errs safe."""
    font, limit, lines = 'Helvetica-Bold' if bold else 'Helvetica', width * 72 / .93, 0
    for part in text.split('\n'):
        used, lines = 0, lines + 1
        for word in part.split():
            need = stringWidth(word + ' ', font, size)
            if stringWidth(word, font, size) > limit:
                return 10000  # an unbreakable label cannot fit at this size
            if used and used + need > limit:
                lines, used = lines + 1, 0
            used += need
    return lines


def _height(text, size, width, bold=False):
    return _wrapped(text, size, width, bold) * size * 1.2 / 72


def _rectangle(slide, x, y, w, h, fill):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _colour(fill)
    shape.line.fill.background()
    shape._element.remove(shape._element.find(qn('p:style')))  # the theme's style carries a shadow
    return shape


def _text(slide, x, y, w, h, runs, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT):
    """`runs` is a list of paragraphs, each (text, size, colour, bold, space before in points)."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap, frame.vertical_anchor = True, anchor
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    for number, (text, size, colour, bold, before) in enumerate(runs):
        paragraph = frame.paragraphs[0] if number == 0 else frame.add_paragraph()
        paragraph.alignment, paragraph.space_before, paragraph.line_spacing = align, Pt(before), 1.0
        run = paragraph.add_run()
        run.text = text
        run.font.name, run.font.size, run.font.bold = FONT, Pt(size), bold
        run.font.color.rgb = _colour(colour)
    return box


def _chrome(slide, title, source, page, note=''):
    size = next((s for s in TITLE_SIZES if _wrapped(title, s, INNER, True) <= 2), None)
    if size is None:
        raise ValueError('the headline does not fit on two lines; shorten it')
    _text(slide, MARGIN, .24, INNER, .9, [(title, size, NAVY, True, 0)], anchor=MSO_ANCHOR.BOTTOM)
    _rectangle(slide, MARGIN, 1.2, INNER, .03, TEAL)
    foot = [note] if note else []
    foot += [f'Source: {source}'] if source else []
    text = '  '.join(foot)
    if _wrapped(text, 10, INNER) > 2:
        raise ValueError('the source footnote does not fit on two lines; cite fewer locations')
    _text(slide, MARGIN, 6.5, INNER, .4, [(text, 10, MUTED, False, 0)])
    _rectangle(slide, MARGIN, 6.96, INNER, .01, RULE)
    _text(slide, MARGIN, 7.02, 10, .22, [(FOOTER, 9, MUTED, False, 0)])
    _text(slide, WIDTH - MARGIN - 1, 7.02, 1, .22, [(str(page), 9, MUTED, False, 0)], align=PP_ALIGN.RIGHT)


def _split(text):
    """Evidence and what it means: a bullet's last sentence is its point when it has more than one."""
    parts = sentences(text)
    return (' '.join(parts[:-1]), parts[-1]) if len(parts) > 1 else ('', text)


def _card_height(text, size, width):
    evidence, point = _split(text)
    height = _height(point, size, width, True)  # bold is the wider case
    return height + (_height(evidence, size, width) + 6 / 72 if evidence else 0)


def _card_runs(kind, text, size):
    """Evidence in plain type, the point in bold navy: an evidence-only bullet has no point to set in bold."""
    evidence, point = _split(text)
    if not evidence and kind == 'evidence':
        return [(point, size, INK, False, 0)]
    return ([(evidence, size, INK, False, 0)] if evidence else []) + [(point, size, NAVY, True, 6 if evidence else 0)]


def _cards(slide, bullets, x, y, w, h, columns):
    """Bullets as cards in a grid; every card shares one type size, the largest at which they all fit."""
    rows = (len(bullets) + columns - 1) // columns
    gap = .18
    card_w, card_h = (w - gap * (columns - 1)) / columns, (h - gap * (rows - 1)) / rows
    inner_w, inner_h = card_w - .46, card_h - .36
    size = next((s for s in CARD_SIZES if all(_card_height(text, s, inner_w) <= inner_h for _, text in bullets)), None)
    if size is None:
        raise ValueError('the bullets do not fit on the slide; shorten them')
    for number, (kind, text) in enumerate(bullets):
        left, top = x + (number % columns) * (card_w + gap), y + (number // columns) * (card_h + gap)
        _rectangle(slide, left, top, card_w, card_h, PANEL)
        _rectangle(slide, left, top, .07, card_h, ACCENT.get(kind, TEAL))
        _text(slide, left + .28, top + .18, inner_w, inner_h, _card_runs(kind, text, size), anchor=MSO_ANCHOR.MIDDLE)


def _columns(count):
    return {1: 1, 2: 2, 3: 3, 4: 2}[count]


def _cover(slide, company, line, bullets, when):
    _rectangle(slide, 0, 0, WIDTH, HEIGHT, NAVY)
    _rectangle(slide, MARGIN + .1, 2.2, .1, 2.1, TEAL)
    if _wrapped(line, 24, 10.6) > 3:
        raise ValueError('the headline does not fit on the cover; shorten it')
    _text(slide, MARGIN + .45, 2.1, 11, 1, [(company, 48, WHITE, True, 0)])
    _text(slide, MARGIN + .45, 3.1, 10.6, 1.25, [(line, 24, 'DCE7F0', False, 0)])
    if bullets:
        runs = [(text, 15, 'B7C7D6', False, 6) for _, text in bullets]
        if sum(_height(text, 15, 10.6) + 6 / 72 for _, text in bullets) > 1.2:
            raise ValueError('the cover evidence does not fit; shorten it')
        _text(slide, MARGIN + .45, 4.55, 10.6, 1.2, runs)
    _text(slide, MARGIN + .45, 6.55, 10.6, .3, [(f'{when}  |  {FOOTER}', 11, 'B7C7D6', False, 0)])


def _notices(slide, notices, page):
    _chrome(slide, 'Important notice', '', page)
    across = 2 if len(notices) <= 4 else 3
    down = max(1, -(-len(notices) // across))
    gap = .18
    x, y, w, h = MARGIN, BODY_TOP, (INNER - gap * (across - 1)) / across, (BODY_BOTTOM + .4 - BODY_TOP - gap * (down - 1)) / down
    inner = w - .46
    size = next((s for s in NOTICE_SIZES if all(_height(text, s, inner) + (s + 3) * 1.3 / 72 <= h - .3 for _, text in notices)), None)
    if size is None:
        raise ValueError('the notices do not fit on one slide')
    for number, (title, text) in enumerate(notices):
        left, top = x + (number % across) * (w + gap), y + (number // across) * (h + gap)
        _rectangle(slide, left, top, w, h, PANEL)
        _rectangle(slide, left, top, .07, h, NAVY)
        _text(slide, left + .28, top + .15, inner, h - .3, [(title, size + 1, NAVY, True, 0), (text, size, INK, False, 4)])


def _waterfall(slide, chart, x, y, w, h):
    """A bridge: totals stand on the axis and each step floats from the level the last one reached. The step's value is printed in its label, because a small step has no room inside its bar."""
    values, kinds = chart['series'][0]['values'], chart['kinds']
    places = chart['decimals']
    base, total, up, down, level = [], [], [], [], 0
    for value, kind in zip(values, kinds):
        if kind == 'total':
            base.append(None), total.append(value), up.append(None), down.append(None)
            level = value
        else:
            base.append(min(level, level + value)), total.append(None)
            up.append(value if value >= 0 else None), down.append(-value if value < 0 else None)
            level += value
    signed = [f'{value:,.{places}f}' if kind == 'total' else f'{value:+,.{places}f}' for value, kind in zip(values, kinds)]
    data = CategoryChartData()
    data.categories = [f'{label}\n{number}' for label, number in zip(chart['categories'], signed)]
    for name, series in (('', base), ('Total', total), ('Increase', up), ('Decrease', down)):
        data.add_series(name, series)
    native = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, Inches(x), Inches(y), Inches(w), Inches(h), data).chart
    native.font.name, native.font.size = FONT, Pt(12)
    native.font.color.rgb = _colour(INK)
    native.has_legend = False
    _caption(native, chart)
    native.value_axis.has_major_gridlines, native.value_axis.visible = False, False
    native.value_axis.minimum_scale = 0
    native.category_axis.tick_label_position, native.category_axis.has_major_gridlines = XL_TICK_LABEL_POSITION.LOW, False
    native.category_axis.format.line.color.rgb = _colour(RULE)
    plot = native.plots[0]
    plot.gap_width, plot.overlap = 45, 100
    native.series[0].format.fill.background()
    native.series[0].format.line.fill.background()
    for series, colour in zip(list(native.series)[1:], (NAVY, TEAL, CORAL)):
        series.invert_if_negative = False
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = _colour(colour)


def _caption(native, chart):
    """A panel beside another needs its own name; one series has no legend to carry it."""
    native.has_title = bool(chart.get('caption'))
    if native.has_title:
        native.chart_title.text_frame.text = chart['caption']
        run = native.chart_title.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.bold, run.font.name = Pt(12), True, FONT
        run.font.color.rgb = _colour(NAVY)
        native.chart_title.include_in_layout = False


def _chart(slide, chart, x, y, w, h):
    if chart['plot'] == 'waterfall':
        return _waterfall(slide, chart, x, y, w, h)
    data = CategoryChartData()
    data.categories = chart['categories']
    for series in chart['series']:
        data.add_series(series['name'], series['values'])
    kind = {'column': XL_CHART_TYPE.COLUMN_CLUSTERED, 'bar': XL_CHART_TYPE.BAR_CLUSTERED, 'line': XL_CHART_TYPE.LINE_MARKERS}[chart['plot']]
    native = slide.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), data).chart
    native.font.name, native.font.size = FONT, Pt(12)
    native.font.color.rgb = _colour(INK)
    _caption(native, chart)
    native.has_legend = len(chart['series']) > 1
    if native.has_legend:
        native.legend.position, native.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
    plot = native.plots[0]
    plot.has_data_labels = True
    labels = plot.data_labels
    places = '0.' + '0' * chart['decimals'] if chart['decimals'] else '0'
    labels.number_format, labels.number_format_is_linked = f'{places};({places})', False
    labels.show_value = True
    labels.position = XL_LABEL_POSITION.ABOVE if chart['plot'] == 'line' else XL_LABEL_POSITION.OUTSIDE_END
    # Two lines that start close together would print their labels on top of each other.
    if chart['plot'] == 'line' and len(chart['series']) > 1:
        below = plot.series[len(chart['series']) - 1].data_labels
        below.show_value, below.position = True, XL_LABEL_POSITION.BELOW
        below.number_format, below.number_format_is_linked = labels.number_format, False
        below.font.size, below.font.name = Pt(11), FONT
    labels.font.size, labels.font.name = Pt(12 if len(chart['series']) == 1 else 11), FONT
    native.value_axis.has_major_gridlines, native.value_axis.visible = False, False
    low, high = min(min(s['values']) for s in chart['series']), max(max(s['values']) for s in chart['series'])
    low, high = min(low, 0), max(high, 0)
    span = (high - low) or 1
    native.value_axis.maximum_scale = high + span * .15
    native.value_axis.minimum_scale = min(low, 0) - (span * .15 if low < 0 else 0)
    axis = native.category_axis
    axis.tick_label_position, axis.has_major_gridlines = XL_TICK_LABEL_POSITION.LOW, False
    axis.format.line.color.rgb = _colour(RULE)
    if chart['plot'] == 'bar':
        axis.reverse_order = True
    if chart['plot'] != 'line':
        plot.gap_width, plot.overlap = 55, -5
    for number, series in enumerate(native.series):
        colour = _colour(SERIES[number])
        if chart['plot'] == 'line':
            series.format.line.color.rgb, series.format.line.width, series.smooth = colour, Pt(2.75), False
            series.marker.format.fill.solid()
            series.marker.format.fill.fore_color.rgb = colour
            series.marker.format.line.color.rgb = colour
        else:
            series.invert_if_negative = False
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = colour


def _hairlines(cell):
    """A rule under the cell and nothing else; PowerPoint and LibreOffice both need the edges stated."""
    properties = cell._tc.get_or_add_tcPr()
    for position, tag in enumerate(('a:lnL', 'a:lnR', 'a:lnT', 'a:lnB')):
        line = OxmlElement(tag)
        line.set('w', '6350' if tag == 'a:lnB' else '0')
        if tag == 'a:lnB':
            fill = OxmlElement('a:solidFill')
            colour = OxmlElement('a:srgbClr')
            colour.set('val', RULE)
            fill.append(colour)
            line.append(fill)
        else:
            line.append(OxmlElement('a:noFill'))
        properties.insert(position, line)


def _table(slide, table, x, y, w, room=None):
    rows, columns = len(table['rows']) + 1, len(table['header'])
    start = 14 if rows <= 7 and w > 8 else 12
    natural = .46 if rows <= 7 else .38
    crowded = False
    usual = min(4.4, w * (.36 if w > 8 else .44))

    def layout(size, first):
        widths = [first] + [(w - first) / (columns - 1)] * (columns - 1)
        if any(_wrapped(cell, size, width - .24, index == 0) > 1 for row in table['rows'] for index, (cell, width) in enumerate(zip(row, widths))):
            return None
        heading = max(_wrapped(cell, size, width - .24, True) for cell, width in zip(table['header'], widths))
        return (widths, heading) if heading <= 2 else None
    # Headings may take two lines and the label column gives way to the figures; only then does the type come down.
    for size in range(start, MIN_TABLE_SIZE - 1, -1):
        label = max(stringWidth(row[0], 'Helvetica-Bold', size) for row in [table['header'], *table['rows']]) * .93 / 72 + .3
        found = layout(size, max(usual, min(label, w * .5))) or layout(size, min(label, w * .5))
        if not found:
            continue
        widths, heading = found
        lines = rows - 1 + heading
        height = min(natural, room / lines) if room else natural
        if height >= size * 1.2 / 72 + .06:
            break
        crowded = True
    else:
        raise ValueError('the table rows do not have room for their text; show fewer rows' if crowded else 'a table row label does not fit on one line; choose fewer columns')
    shape = slide.shapes.add_table(rows, columns, Inches(x), Inches(y), Inches(w), Inches(height * lines))
    native = shape.table
    # No built-in table style: the fills below are the whole look.
    shape._element.graphic.graphicData.tbl.tblPr.remove(shape._element.graphic.graphicData.tbl.tblPr.find(
        '{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId'))
    for index, width in enumerate(widths):
        native.columns[index].width = Inches(width)
    for row_index, row in enumerate([table['header']] + table['rows']):
        native.rows[row_index].height = Inches(height * (heading if row_index == 0 else 1))
        for column, value in enumerate(row):
            cell = native.cell(row_index, column)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Inches(.12)
            cell.margin_top = cell.margin_bottom = Inches(.03)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _colour(NAVY if row_index == 0 else PANEL if row_index % 2 == 0 else WHITE)
            _hairlines(cell)
            paragraph = cell.text_frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.LEFT if column == 0 else PP_ALIGN.RIGHT
            run = paragraph.add_run()
            run.text = value
            run.font.name, run.font.size, run.font.bold = FONT, Pt(size), row_index == 0 or (column == 0 and bool(row_index))
            run.font.color.rgb = _colour(WHITE if row_index == 0 else NAVY if column == 0 else INK)
    return height * lines


def draw_slide(slide, spec, page):
    """Draw one content slide. `spec` holds heading, bullets [(kind, text)], source, and optional chart or table."""
    chart, table = spec.get('chart'), spec.get('table')
    _chrome(slide, spec['heading'], spec['source'], page, spec.get('note', ''))
    bullets, height = spec['bullets'], BODY_BOTTOM - BODY_TOP
    if chart:
        _chart(slide, chart, MARGIN - .05, BODY_TOP - .05, CHART_WIDTH, height + .1)
        right = MARGIN + CHART_WIDTH + .2
        if bullets:
            _cards(slide, bullets, right, BODY_TOP, WIDTH - MARGIN - right, height, 1)
    elif table:
        top = BODY_TOP
        if bullets:
            strip = 1.25
            _cards(slide, bullets, MARGIN, top, INNER, strip, _columns(len(bullets)))
            top += strip + .2
        if top + (len(table['rows']) + 1) * (.46 if len(table['rows']) < 7 else .38) > BODY_BOTTOM:
            raise ValueError('the table does not fit below the bullets; show fewer rows')
        _table(slide, table, MARGIN, top, INNER, BODY_BOTTOM - top)
    else:
        if not bullets:
            raise ValueError('the slide has no content')
        _cards(slide, bullets, MARGIN, BODY_TOP, INNER, height, _columns(len(bullets)))


def _kpis(slide, kpis, y):
    """The headline measures in a strip, value first, as the eye reads them."""
    gap = .14
    width = (INNER - gap * (len(kpis) - 1)) / len(kpis)
    def needed(kpi, size):
        return (_height(kpi['label'], 12, width - .3, True) + _height(kpi['value'], size, width - .3, True) +
                _height(kpi['sub'], 11, width - .3) + 4 / 72 + .24)

    size = next((s for s in (24, 22, 20, 18, 16) if all(
        _wrapped(kpi['value'], s, width - .3, True) == 1 and
        needed(kpi, s) <= 1.5 for kpi in kpis)), None)
    if size is None:
        raise ValueError('the measures do not fit in the KPI strip; shorten their labels or show fewer measures')
    height = max(KPI_HEIGHT, max(needed(kpi, size) for kpi in kpis))
    for number, kpi in enumerate(kpis):
        left = MARGIN + number * (width + gap)
        _rectangle(slide, left, y, width, height, PANEL)
        _rectangle(slide, left, y, width, .05, TEAL)
        _text(slide, left + .15, y + .12, width - .3, height - .24,
              [(kpi['label'], 12, MUTED, True, 0), (kpi['value'], size, NAVY, True, 2), (kpi['sub'], 11, MUTED, False, 2)])
    return height


def _grid(slide, grid, x, y, w, h):
    """A table of words: its rows grow to fit, and it is refused if it cannot fit at the smallest size."""
    columns = len(grid['header'])
    weights = grid.get('weights') or [1] * columns
    if len(weights) != columns or any(weight <= 0 for weight in weights) or any(len(row) != columns for row in grid['rows']):
        raise ValueError('the grid columns and widths do not match')
    widths = [w * weight / sum(weights) for weight in weights]

    def row_height(row, size):
        return max(_wrapped(cell or ' ', size, width - .24, row is grid['header'] or index == 0) for index, (cell, width) in enumerate(zip(row, widths))) * size * 1.2 / 72 + .16
    size = next((s for s in (15, 14, 13, 12, 11, 10) if sum(row_height(row, s) for row in [grid['header']] + grid['rows']) <= h), None)
    if size is None:
        raise ValueError('the grid does not fit on the page; show fewer rows')
    heights = [row_height(row, size) for row in [grid['header']] + grid['rows']]
    shape = slide.shapes.add_table(len(heights), columns, Inches(x), Inches(y), Inches(w), Inches(sum(heights)))
    native = shape.table
    properties = shape._element.graphic.graphicData.tbl.tblPr
    properties.remove(properties.find('{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId'))
    for index, width in enumerate(widths):
        native.columns[index].width = Inches(width)
    for row_index, row in enumerate([grid['header']] + grid['rows']):
        native.rows[row_index].height = Inches(heights[row_index])
        for column, value in enumerate(row):
            cell = native.cell(row_index, column)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Inches(.12)
            cell.margin_top = cell.margin_bottom = Inches(.04)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _colour(NAVY if row_index == 0 else PANEL if row_index % 2 == 0 else WHITE)
            _hairlines(cell)
            cell.text_frame.word_wrap = True
            paragraph = cell.text_frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.RIGHT if column in grid.get('numeric', []) else PP_ALIGN.LEFT
            run = paragraph.add_run()
            run.text = value
            run.font.name, run.font.size, run.font.bold = FONT, Pt(size), row_index == 0 or column == 0
            run.font.color.rgb = _colour(WHITE if row_index == 0 else NAVY if column == 0 else INK)


def _divider(slide, heading, page):
    size = next((size for size in (48, 44, 40, 36) if _height(heading, size, 10.6, True) <= 1.6), None)
    if size is None:
        raise ValueError('the section title does not fit on the divider; shorten it')
    _rectangle(slide, 0, 0, WIDTH, HEIGHT, NAVY)
    _rectangle(slide, MARGIN + .1, 2.2, .1, 2.1, TEAL)
    _text(slide, MARGIN + .45, 2.5, 10.6, 1.6, [(heading, size, WHITE, True, 0)])
    _text(slide, MARGIN + .45, 6.55, 10.6, .3, [(FOOTER, 11, 'B7C7D6', False, 0)])
    _text(slide, WIDTH - MARGIN - 1, 7.02, 1, .22, [(str(page), 9, 'B7C7D6', False, 0)], align=PP_ALIGN.RIGHT)


def _summary(slide, summary, top, height):
    left_width = INNER * .64
    for key, title, x, width in (('highlights', 'Investment highlights', MARGIN, left_width),
                                 ('risks', 'Key risks', MARGIN + left_width + .2, INNER - left_width - .2)):
        _text(slide, x, top, width, .3, [(title, 16, NAVY, True, 0)])
        grid = summary[key]
        if grid['rows']:
            _grid(slide, grid, x, top + .4, width, height - .4)
        else:
            text = 'Evidence-backed merits and proofs needed.' if key == 'highlights' else 'Reviewed risk titles needed.'
            if _height(text, 12, width) > height - .4:
                raise ValueError('the executive summary does not fit on the page')
            _text(slide, x, top + .4, width, height - .4, [(text, 12, MUTED, False, 0)])


def draw_page(slide, spec, page):
    """One memorandum page: an optional strip of measures, a main exhibit, and short takeaways beside or below it."""
    if spec.get('divider'):
        return _divider(slide, spec['heading'], page)
    _chrome(slide, spec['heading'], spec['source'], page, spec.get('note', ''))
    top, bullets = BODY_TOP, spec['bullets']
    if spec.get('kpis'):
        top += _kpis(slide, spec['kpis'], top) + .16
    elif spec.get('summary'):
        _text(slide, MARGIN, top, INNER, .3, [('Headline measures: cited financial measures needed.', 12, MUTED, False, 0)])
        top += .4
    height = BODY_BOTTOM - top
    if spec.get('summary'):
        return _summary(slide, spec['summary'], top, height)
    chart, table, grid = spec.get('chart'), spec.get('table'), spec.get('grid')
    if chart and spec.get('chart2'):
        half = (INNER - .2) / 2
        strip = 1.1 if bullets else 0
        room = height - strip - (.12 if bullets else 0)
        _chart(slide, chart, MARGIN - .05, top - .05, half, room + .05)
        _chart(slide, spec['chart2'], MARGIN + half + .2, top - .05, half, room + .05)
        if bullets:
            _cards(slide, bullets, MARGIN, BODY_BOTTOM - strip, INNER, strip, len(bullets))
    elif chart and (table or grid):
        half = (INNER - .2) / 2
        strip = 1.1 if bullets else 0
        room = height - strip - (.16 if bullets else 0)
        _chart(slide, chart, MARGIN - .05, top - .05, half, room + .05)
        if table:
            _table(slide, table, MARGIN + half + .2, top, half, room)
        else:
            _grid(slide, grid, MARGIN + half + .2, top, half, room)
        if bullets:
            _cards(slide, bullets, MARGIN, BODY_BOTTOM - strip, INNER, strip, len(bullets))
    elif chart:
        _chart(slide, chart, MARGIN - .05, top - .05, CHART_WIDTH if bullets else INNER + .1, height + .1)
        if bullets:
            right = MARGIN + CHART_WIDTH + .2
            _cards(slide, bullets, right, top, WIDTH - MARGIN - right, height, 1)
    elif table or grid:
        strip = 1.1 if bullets else 0
        room = height - strip - (.16 if bullets else 0)
        if table:
            if (len(table['rows']) + 1) * .3 > room:
                raise ValueError('the table does not fit on the page; show fewer rows')
            _table(slide, table, MARGIN, top, INNER, room)
        else:
            _grid(slide, grid, MARGIN, top, INNER, room)
        if bullets:
            _cards(slide, bullets, MARGIN, BODY_BOTTOM - strip, INNER, strip, len(bullets))
    elif bullets:
        _cards(slide, bullets, MARGIN, top, INNER, height, _columns(len(bullets)))


def trial_page(spec):
    """Draw one page and discard it; raises ValueError when it cannot be drawn."""
    deck, blank = _new()
    draw_page(deck.slides.add_slide(blank), spec, 1)


def build_pages(cover, notices, pages, title):
    deck, blank = _new()
    deck.core_properties.title, deck.core_properties.author = title, ''
    _cover(deck.slides.add_slide(blank), cover['company'], cover['heading'], cover['bullets'], cover['when'])
    _notices(deck.slides.add_slide(blank), notices, 2)
    for page, spec in enumerate(pages, 3):
        draw_page(deck.slides.add_slide(blank), spec, page)
    output = BytesIO()
    deck.save(output)
    return output.getvalue()


def _new():
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(WIDTH), Inches(HEIGHT)
    return deck, deck.slide_layouts[6]


def trial(spec):
    """Draw one slide and discard it; raises ValueError when it cannot be drawn."""
    deck, blank = _new()
    draw_slide(deck.slides.add_slide(blank), spec, 1)


def build_pptx(cover, notices, slides, title):
    deck, blank = _new()
    deck.core_properties.title, deck.core_properties.author = title, ''
    _cover(deck.slides.add_slide(blank), cover['company'], cover['heading'], cover['bullets'], cover['when'])
    _notices(deck.slides.add_slide(blank), notices, 2)
    for page, spec in enumerate(slides, 3):
        draw_slide(deck.slides.add_slide(blank), spec, page)
    output = BytesIO()
    deck.save(output)
    return output.getvalue()


def to_pdf(data: bytes, suffix: str = 'pptx') -> bytes:
    """The PDF of exactly this Office file, so the two cannot differ."""
    with tempfile.TemporaryDirectory(prefix='deck-pdf-') as folder:
        source = Path(folder) / f'deck.{suffix}'
        source.write_bytes(data)
        os.chmod(source, 0o600)
        subprocess.run(['soffice', f'-env:UserInstallation=file://{folder}/profile', '--headless', '--convert-to', 'pdf',
                        '--outdir', folder, str(source)], check=True, capture_output=True, timeout=CONVERT_TIMEOUT)
        return (Path(folder) / 'deck.pdf').read_bytes()
