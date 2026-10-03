"""Job-local parser/renderer entry point. Invoked through delivery.isolation only."""
import json
import sys
from pathlib import Path

from delivery.inspection import inspect_bytes, inspect_export_pair
from delivery.rendering import (render_intro, render_deck_pdf, render_memo,
                                render_memo_pdf, render_research_pdf)


def main():
    job=Path.cwd()
    request=json.loads((job/'request.json').read_text())
    if request['operation']=='inspect':
        report=inspect_bytes((job/'input.bin').read_bytes(),request['format'])
        (job/'result.json').write_text(json.dumps(report))
    elif request['operation']=='render':
        memo_sections=request['memo_sections']
        intro_sections=request['intro_sections']
        pitch_sections=request['pitch_sections']
        if intro_sections == pitch_sections:
            raise ValueError('Intro and pitch material specs are identical')
        title=request['title']
        # These are draft views of the accepted, replayed model sections. No
        # renderer adds company facts, figures, or a financial chart.
        outputs={
            'intro.pptx': render_intro(title,intro_sections),
            'intro.pdf': render_deck_pdf(title,intro_sections),
            'pitch.pptx': render_intro(title,pitch_sections),
            'pitch.pdf': render_deck_pdf(title,pitch_sections),
            'memo.docx': render_memo(title,memo_sections),
            'memo.pdf': render_memo_pdf(title,memo_sections),
            'research.pdf': render_research_pdf(title,memo_sections),
        }
        for stem,editable in (('intro','pptx'),('pitch','pptx'),('memo','docx')):
            pair=inspect_export_pair(outputs[f'{stem}.{editable}'],editable,
                                     outputs[f'{stem}.pdf'])
            if pair['pair_status']!='pass' or pair['editable_text_status']!='pass':
                raise ValueError(f'{stem}_export_pair_failed')
        for name,content in outputs.items():
            (job/name).write_bytes(content)
    else:
        raise ValueError('Unsupported private operation')


if __name__=='__main__':main()
