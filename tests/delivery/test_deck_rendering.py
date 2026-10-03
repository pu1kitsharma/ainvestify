"""Synthetic checks for editable deck geometry and matching PDF pages."""

from io import BytesIO
import re

import pytest
from pptx import Presentation
from pypdf import PdfReader

from delivery.inspection import inspect_export_pair
from delivery.rendering import render_deck_pdf, render_intro


SECTIONS = [
    ('Synthetic offering', 'A cited synthetic service description [S1].',
     '[S1] Synthetic public fixture.', 'statement'),
    ('Synthetic evidence', 'The source reports a limited synthetic pilot [S1].',
     '[S1] Synthetic pilot record, dated 2025.', 'evidence'),
    ('Synthetic comparison', 'The source describes product A [S1]. '
     'The source separately describes product B [S2].',
     '[S1] Synthetic product A. [S2] Synthetic product B.', 'comparison'),
    ('Synthetic chronology', 'In 2024, the synthetic pilot began [S1]. '
     'In 2025, it remained under review [S2].',
     '[S1] Synthetic 2024 record. [S2] Synthetic 2025 record.', 'timeline'),
]


def test_deck_pdf_and_editable_slides_preserve_model_text_and_layout():
    pptx = render_intro('Synthetic company', SECTIONS)
    pdf = render_deck_pdf('Synthetic company', SECTIONS)
    deck = Presentation(BytesIO(pptx))
    pages = PdfReader(BytesIO(pdf)).pages
    assert len(deck.slides) == len(pages) == 4
    assert round(deck.slide_width / deck.slide_height, 2) == 1.78
    for slide, page, (heading, body, sources, _) in zip(deck.slides, pages, SECTIONS):
        editable_text = '\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame)
        pdf_text = page.extract_text()
        for value in (heading, sources):
            assert value in editable_text
            assert value in pdf_text
        for phrase in body.split('. '):
            assert phrase in editable_text
            assert phrase in re.sub(r'\s+', ' ', pdf_text)
        assert 'DRAFT' in editable_text and 'SOURCE NOTES' in editable_text
        assert len([shape for shape in slide.shapes if shape.has_text_frame]) >= 6
    assert inspect_export_pair(pptx, 'pptx', pdf)['pair_status'] == 'pass'


def test_deck_pdf_rejects_text_that_would_not_fit_editable_box():
    excessive_sources = '[S1] ' + 'Synthetic dated evidence. ' * 40
    with pytest.raises(ValueError, match='Deck PDF text exceeds'):
        render_deck_pdf('Synthetic company', [
            ('Synthetic claim', 'Recorded synthetic statement [S1].',
             excessive_sources, 'statement')])
