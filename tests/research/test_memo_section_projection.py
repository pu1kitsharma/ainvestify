"""Reader-facing layout of an accepted memo: structured records as fields, sources once.

Synthetic sources and a scripted double only. The layout is versioned; a run
recorded without a version keeps its original sections exactly.
"""
import hashlib
import json

import pytest

from agents.research.investment_memo import (FRESH_SECTION_PROJECTION, SECTION_PROJECTIONS,
                                             Source, generate_memo, readable_excerpt,
                                             renderable_sections)
from tests.research.test_investment_memo import (QUOTE, SOURCE, FakeLocalModel, draft,
                                                 passing_review)

RECORD = {'company': 'Example Labs', 'label': 'Seed', 'date': '2025-06',
          'amount': 'USD 100000', 'status': 'unknown'}
RECORD_SOURCE = Source(id='S2', url='https://example.invalid/registry', title='Registry',
                       passage=json.dumps(RECORD, separators=(',', ':')),
                       version='registry-v1', attribution='Synthetic registry')
SOURCES = [SOURCE, RECORD_SOURCE]
LEGACY = '9c7153ef00317fc0afd4ac22138538f978afe0f99dcfdc4e43f73d3b242b8bf8'
ASSERTION = 'A registry lists a seed financing entry dated 2025-06 with unknown status.'


def accepted():
    output = draft()
    output['risks_and_countercase']['claims'] = [
        {'source_id': 'S2', 'quote': RECORD_SOURCE.passage, 'assertion': ASSERTION}]
    output['risks_and_countercase']['analysis'] = (
        'A registry lists a seed financing entry with unknown status [S2]. The entry is a source '
        'report and does not show that the round closed or that the company holds the cash, so '
        'available capital may be lower than the listing implies until records are obtained.')
    review = passing_review()
    attempts = []
    result = generate_memo('Example Labs', SOURCES, model=FakeLocalModel([output, review]),
                           attempts=attempts, save=lambda: None)
    return result, attempts, output


def test_structured_record_is_shown_as_fields_and_never_as_raw_json():
    result, attempts, output = accepted()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v1')
    risks = next(body for heading, body, _ in sections if heading == 'Risks and countercase')
    assert '{' not in risks and '"' not in risks
    # The model's prose and its claim assertion are unchanged, in place.
    assert risks.startswith(output['risks_and_countercase']['analysis'])
    assert risks.endswith(
        f'\n\nSource claims and exact excerpts:\n[S2] {ASSERTION} Source record: '
        'company: Example Labs; label: Seed; date: 2025-06; amount: USD 100000; status: unknown.')
    # Every key and value of the record is shown; nothing else is added to the body.
    for key, value in RECORD.items():
        assert f'{key}: {value}' in risks
    # A prose quote is still shown exactly, labelled as an exact excerpt.
    thesis = next(body for heading, body, _ in sections if heading == 'Investment thesis')
    assert thesis.endswith('Exact excerpt: ' + QUOTE)
    assert not any('{"' in body for _, body, _ in sections)


@pytest.mark.parametrize('quote, shown', [
    ('{"status":"unknown","amount":"INR 20 crore"}',
     'Source record: status: unknown; amount: INR 20 crore.'),
    # A run of key/value pairs from inside a record.
    ('"label":"Seed","date":"2025-06"', 'Source record: label: Seed; date: 2025-06.'),
    # Numbers keep their written form; null, booleans, nesting and lists are laid out.
    ('{"amount":20.50,"count":007e0,"round_type":"seed"}'.replace('007e0', '7'),
     'Source record: amount: 20.50; count: 7; round type: seed.'),
    ('{"closed":false,"lead":null,"terms":{"currency":"USD","tranches":[1,2]},'
     '"rounds":[{"label":"Seed"},{"label":"A"}],"tags":[]}',
     'Source record: closed: false; lead: not given; terms currency: USD; terms tranches: 1, 2; '
     'rounds 1 label: Seed; rounds 2 label: A; tags: none.'),
    # Not a record: left exactly as quoted, braces and all.
    ('The company {sic} reports one pilot with a clinic.',
     'Exact excerpt: The company {sic} reports one pilot with a clinic.'),
    ('{"company":"Example Labs","label":"Seed","date":"2025-06"',
     'Exact excerpt: {"company":"Example Labs","label":"Seed","date":"2025-06"'),
    ('["Seed","Series A"] were listed by the registry.',
     'Exact excerpt: ["Seed","Series A"] were listed by the registry.'),
    ('{}', 'Exact excerpt: {}'),
])
def test_readable_excerpt_lays_out_records_and_leaves_other_quotes_exact(quote, shown):
    assert readable_excerpt(quote) == shown


def test_source_urls_and_versions_appear_once_not_in_every_section():
    result, attempts, _ = accepted()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v1')
    legacy = renderable_sections(result, SOURCES, attempts)
    everything = '\n'.join(f'{heading}\n{body}\n{sources}' for heading, body, sources in sections)
    for source in SOURCES:
        assert everything.count(source.url) == 1 and everything.count(source.version) == 1
    old = '\n'.join(sources for _, _, sources in legacy)
    assert old.count(SOURCE.url) >= 5 and old.count('version ' + SOURCE.version) >= 5
    # Each section still names the sources it relies on, by ID, for readers and for
    # the deck stage, which reads the IDs from this field.
    by_heading = {heading: sources for heading, _, sources in sections}
    assert by_heading['Investment thesis'] == f'[S1] {SOURCE.attribution}'
    assert by_heading['Risks and countercase'] == '[S2] Synthetic registry'
    # The full list closes the memo, in source order, one line per cited source.
    heading, body, sources = sections[-1]
    assert heading == 'Sources and retained versions' and sources == ''
    assert body.splitlines() == [
        f'[S1] {SOURCE.url} | {SOURCE.attribution} | version {SOURCE.version}',
        '[S2] https://example.invalid/registry | Synthetic registry | version registry-v1']
    assert len(sections) == len(legacy) + 1
    # Pinned: profiles frozen as reader_v1 keep this layout exactly.
    assert hashlib.sha256(json.dumps(sections, ensure_ascii=False).encode()).hexdigest() == (
        'b2e9531b7071c734967e9c80acba43cb1a92307dd8f8e9731ad7553dc10da766')
    assert all(heading and body and len(body) <= 1200 and len(sources) <= 1200
               for heading, body, sources in sections)
    # Only the layout differs: headings and model prose are the recorded ones.
    assert [heading for heading, _, _ in sections[:-1]] == [heading for heading, _, _ in legacy]
    marker = '\n\nSource claims and exact excerpts:\n'
    assert [body.partition(marker)[0] for _, body, _ in sections[:-1]] == [
        body.partition(marker)[0] for _, body, _ in legacy]


def test_a_long_source_list_is_split_between_whole_lines():
    passage = 'Example Labs describes a scheduling tool for clinics and a pilot with one clinic.'
    many = [Source(id=f'S{index}', url=f'https://example.invalid/{"path" * 30}/{index}',
                   title='Synthetic page', passage=passage, version=f'synthetic-version-{index}',
                   attribution=f'Synthetic page {index}') for index in range(1, 13)]
    output = draft()
    for index, key in enumerate(('investment_thesis', 'business_and_market',
                                 'differentiation_and_execution', 'risks_and_countercase',
                                 'diligence_plan')):
        ids = [f'S{number}' for number in range(index * 2 + 2, index * 2 + 4)]
        output[key]['claims'] = [{'source_id': source_id, 'quote': passage,
                                  'assertion': output[key]['claims'][0]['assertion']}
                                 for source_id in ids]
        output[key]['analysis'] = output[key]['analysis'].replace(
            '[S1]', ''.join(f'[{source_id}]' for source_id in ids))
    attempts = []
    result = generate_memo('Example Labs', many, model=FakeLocalModel([output, passing_review()]),
                           attempts=attempts, save=lambda: None)
    sections = renderable_sections(result, many, attempts, projection='reader_v1')
    tail = [item for item in sections if item[0].startswith('Sources and retained versions')]
    assert len(tail) >= 2 and tail == sections[-len(tail):]
    assert [heading for heading, _, _ in tail] == ['Sources and retained versions'] + [
        'Sources and retained versions (continued)'] * (len(tail) - 1)
    lines = [line for _, body, _ in tail for line in body.splitlines()]
    assert [line.split(' ', 1)[0] for line in lines] == [f'[S{index}]' for index in range(1, 12)]
    assert all(line.endswith(f'version synthetic-version-{line[2:line.index("]")]}')
               for line in lines) and all(len(body) <= 1150 for _, body, _ in tail)


def test_unversioned_run_keeps_its_recorded_layout_byte_for_byte():
    result, attempts, _ = accepted()
    legacy = renderable_sections(result, SOURCES, attempts)
    assert legacy == renderable_sections(result, SOURCES, attempts, projection=None)
    # Pinned: the first layout cannot drift, since saved material requests bind its digest.
    assert hashlib.sha256(json.dumps(legacy, ensure_ascii=False).encode()).hexdigest() == LEGACY
    risks = next(body for heading, body, _ in legacy if heading == 'Risks and countercase')
    assert risks.endswith('Exact excerpt: ' + RECORD_SOURCE.passage)
    assert legacy[-1][0] != 'Sources and retained versions'
    assert SECTION_PROJECTIONS == (None, 'reader_v1', 'reader_v2')
    with pytest.raises(ValueError, match='Unknown memo section projection'):
        renderable_sections(result, SOURCES, attempts, projection='reader_v9')


def test_reader_layout_still_renders_only_the_exact_reviewed_memo():
    result, attempts, _ = accepted()
    forged = json.loads(json.dumps(result))
    forged['memo']['risks_and_countercase']['claims'][0]['assertion'] = (
        'A registry confirms that the seed round closed and the cash was received.')
    with pytest.raises(ValueError):
        renderable_sections(forged, SOURCES, attempts, projection='reader_v1')
    attempts[0]['raw_response'] = '{}'
    with pytest.raises(ValueError, match='modified'):
        renderable_sections(result, SOURCES, attempts, projection='reader_v1')


def test_new_run_profiles_freeze_the_reader_layout_and_old_profiles_do_not(tmp_path):
    from delivery.investment_memo_stage import frozen_memo_model_profile
    fresh = frozen_memo_model_profile(tmp_path / 'model.json', 'qwen3.5:9b')
    assert fresh['section_projection'] == FRESH_SECTION_PROJECTION and fresh['profile_version'] == 4
    assert fresh['memo_draft_contract'] == 'memo-cards-v2'
    assert frozen_memo_model_profile(tmp_path / 'model.json', 'qwen3.5:9b') == fresh
    # A profile saved before the layout was versioned is returned as saved.
    old = {key: value for key, value in fresh.items() if key != 'section_projection'}
    (tmp_path / 'old.json').write_text(json.dumps(old))
    saved = frozen_memo_model_profile(tmp_path / 'old.json', 'qwen3.5:9b')
    assert saved == old and saved.get('section_projection') is None
    assert json.loads((tmp_path / 'old.json').read_text()) == old


def test_reader_sections_render_to_a_matching_editable_and_pdf_memo():
    from delivery.inspection import inspect_export_pair
    from delivery.rendering import render_memo, render_memo_pdf
    result, attempts, _ = accepted()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v1')
    pair = inspect_export_pair(render_memo('Example Labs', sections), 'docx',
                               render_memo_pdf('Example Labs', sections))
    assert pair['pair_status'] == 'pass'


# ---- reader_v2: prose sections, one evidence appendix, one bibliography

READER_V2 = 'a1a99aeb398158a384a0cb9b19471b11a060d36a69cc0d46b8066799fc8c69e1'
MARKER = '\n\nSource claims and exact excerpts:\n'
SECOND = 'The source describes a pilot with one clinic and reports no repeat order.'


def accepted_v2(change=None, sources=SOURCES):
    output = draft()
    output['risks_and_countercase']['claims'] = [
        {'source_id': 'S2', 'quote': RECORD_SOURCE.passage, 'assertion': ASSERTION}]
    output['risks_and_countercase']['analysis'] = (
        'A registry lists a seed financing entry with unknown status [S2]. The entry is a source '
        'report and does not show that the round closed or that the company holds the cash, so '
        'available capital may be lower than the listing implies until records are obtained.')
    # The same quote supports a second, different assertion in another section.
    output['diligence_plan']['claims'].append(
        {'source_id': 'S1', 'quote': QUOTE, 'assertion': SECOND})
    if change:
        change(output)
    attempts = []
    result = generate_memo('Example Labs', sources, model=FakeLocalModel([output, passing_review()]),
                           attempts=attempts, save=lambda: None)
    return result, attempts, output


def model_claims(output):
    return [(claim['source_id'], claim['assertion'], claim['quote'])
            for claims in ([output['recommendation_claims']] + [
                output[key]['claims'] for key in (
                    'investment_thesis', 'business_and_market', 'differentiation_and_execution',
                    'risks_and_countercase', 'diligence_plan')])
            for claim in claims]


def split_sections(sections):
    appendix = [item for item in sections if item[0].startswith('Evidence appendix')]
    bibliography = [item for item in sections if item[0].startswith('Sources and retained')]
    prose = sections[:len(sections) - len(appendix) - len(bibliography)]
    assert sections == prose + appendix + bibliography          # in this order, at the end
    return prose, appendix, bibliography


def test_reader_v2_keeps_exact_prose_and_moves_each_claim_once_to_the_appendix():
    result, attempts, output = accepted_v2()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    prose, appendix, bibliography = split_sections(sections)
    # Sections are the model's prose, exactly, with no claim block and no JSON.
    assert [(heading, body) for heading, body, _ in prose[:6]] == [
        ('Defer Pending Evidence', output['recommendation_reason'])] + [
        (output[key]['heading'], output[key]['analysis']) for key in (
            'investment_thesis', 'business_and_market', 'differentiation_and_execution',
            'risks_and_countercase', 'diligence_plan')]
    assert not any('Source claims' in body or 'Exact excerpt' in body or '{' in body
                   for _, body, _ in prose)
    # Each section still names the sources its prose and claims rely on.
    by_heading = {heading: sources for heading, _, sources in prose}
    assert by_heading['Risks and countercase'] == '[S2] Synthetic registry'
    assert by_heading['Diligence plan'] == f'[S1] {SOURCE.attribution}'
    # Appendix: seven model claims, three distinct assertions over two distinct quotes.
    claims = model_claims(output)
    assert len(claims) == 7 and len(set(claims)) == 3
    (heading, body, sources), = appendix
    assert heading == 'Evidence appendix' and body.startswith(MARKER)
    assert body[len(MARKER):].splitlines() == [
        '[S1] The source reports a scheduling tool for clinics and a pilot with one clinic.',
        f'[S1] {SECOND}',
        f'[S1] Exact excerpt: {QUOTE}',
        f'[S2] {ASSERTION}',
        '[S2] Source record: company: Example Labs; label: Seed; date: 2025-06; '
        'amount: USD 100000; status: unknown.']
    assert sources == f'[S1] {SOURCE.attribution}\n[S2] Synthetic registry'
    # No claim is dropped and none is repeated.
    everything = '\n'.join(body for _, body, _ in sections)
    for source_id, assertion, quote in set(claims):
        assert everything.count(f'[{source_id}] {assertion}') == 1
    assert everything.count(QUOTE) == 1 and everything.count('status: unknown') == 1
    # One bibliography, after the appendix.
    (heading, body, sources), = bibliography
    assert body.splitlines() == [
        f'[S1] {SOURCE.url} | {SOURCE.attribution} | version {SOURCE.version}',
        '[S2] https://example.invalid/registry | Synthetic registry | version registry-v1']
    assert '\n'.join(f'{b}\n{s}' for _, b, s in sections).count(SOURCE.url) == 1


def test_reader_v2_splits_long_prose_only_after_a_sentence_and_drops_nothing():
    sentence = ('The source describes a scheduling tool and one pilot [S1], and the record does '
                'not establish repeat demand, earned revenue, retention or an attractive price. ')
    long_analysis = (sentence * 11).strip()
    assert 1200 < len(long_analysis) <= 1800

    def change(output):
        output['investment_thesis']['analysis'] = long_analysis

    result, attempts, _ = accepted_v2(change)
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    parts = [body for heading, body, _ in sections if heading.startswith('Investment thesis')]
    assert len(parts) == 2 and ''.join(parts) == long_analysis      # every character, in order
    assert parts[0].rstrip().endswith('price.') and parts[1].startswith('The source describes')
    assert all(len(part) <= 1150 for part in parts)
    # The earlier layouts cut at the last space; they are unchanged.
    old = [body for heading, body, _ in renderable_sections(result, SOURCES, attempts,
                                                            projection='reader_v1')
           if heading.startswith('Investment thesis')]
    assert not old[0].rstrip().endswith('.')


def test_reader_v2_appendix_and_records_are_split_only_between_whole_lines():
    record = {f'field_{index}': f'synthetic value number {index} of the registry row'
              for index in range(1, 12)}
    passages = {f'S{index}': json.dumps({**record, 'row': str(index)}, separators=(',', ':'))
                for index in range(2, 8)}
    sources = [SOURCE] + [Source(id=source_id, url=f'https://example.invalid/row/{source_id}',
                                 title='Registry row', passage=passage,
                                 version=f'registry-{source_id}', attribution=f'Registry {source_id}')
                          for source_id, passage in passages.items()]

    def change(output):
        ids = list(passages)
        # This source set has its own S2, so the shared registry claim is put back.
        output['risks_and_countercase'] = draft()['risks_and_countercase']
        for index, key in enumerate(('investment_thesis', 'business_and_market',
                                     'differentiation_and_execution')):
            pair = ids[index * 2:index * 2 + 2]
            output[key]['claims'] = [
                {'source_id': source_id, 'quote': passages[source_id],
                 'assertion': f'The registry row lists synthetic fields for entry {source_id}.'}
                for source_id in pair]
            output[key]['analysis'] = output[key]['analysis'].replace(
                '[S1]', ''.join(f'[{source_id}]' for source_id in pair))

    result, attempts, output = accepted_v2(change, sources)
    sections = renderable_sections(result, sources, attempts, projection='reader_v2')
    prose, appendix, bibliography = split_sections(sections)
    assert len(appendix) >= 3
    assert [heading for heading, _, _ in appendix] == ['Evidence appendix'] + [
        'Evidence appendix (continued)'] * (len(appendix) - 1)
    lines = []
    for _, body, section_sources in appendix:
        assert body.startswith(MARKER) and len(body) <= 1200
        page = body[len(MARKER):].splitlines()
        # Every line on a page is whole: a tagged assertion or a complete record.
        assert all(line.startswith('[S') and line.endswith('.') for line in page)
        # The page's source field names exactly the sources on that page.
        assert [line.split(' ', 1)[0] for line in section_sources.splitlines()] == list(
            dict.fromkeys(line.split(' ', 1)[0] for line in page))
        lines += page
    for source_id, passage in passages.items():
        shown = [line for line in lines if line.startswith(f'[{source_id}] Source record: ')]
        assert len(shown) == 1 and shown[0].endswith(f'; row: {source_id[1:]}.')
        assert all(f'{key.replace("_", " ")}: {value}' in shown[0] for key, value in record.items())
        # An assertion sits on the same page as, and directly before, its record.
        index = lines.index(shown[0])
        assert lines[index - 1] == (
            f'[{source_id}] The registry row lists synthetic fields for entry {source_id}.')
        assert any(shown[0] in body and lines[index - 1] in body for _, body, _ in appendix)
    claims = set(model_claims(output))
    assert len([line for line in lines if 'Source record: ' in line or 'Exact excerpt: ' in line]
               ) == len({(source_id, quote) for source_id, _, quote in claims})
    assert len(lines) == len({(source_id, assertion) for source_id, assertion, _ in claims}) + len(
        {(source_id, quote) for source_id, _, quote in claims})
    assert not any('{"' in body for _, body, _ in sections)
    assert len(bibliography) >= 1 and sum(len(body.splitlines()) for _, body, _ in bibliography) == 7


def test_reader_v2_replays_exactly_and_the_earlier_layouts_are_untouched():
    result, attempts, _ = accepted()
    v2 = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    assert v2 == renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    saved = json.loads(json.dumps(v2, ensure_ascii=False))            # as a stage stores it
    assert [list(item) for item in v2] == saved
    assert hashlib.sha256(json.dumps(v2, ensure_ascii=False).encode()).hexdigest() == READER_V2
    digest_of = lambda projection: hashlib.sha256(json.dumps(renderable_sections(
        result, SOURCES, attempts, projection=projection), ensure_ascii=False).encode()).hexdigest()
    assert digest_of(None) == LEGACY
    assert digest_of('reader_v1') == (
        'b2e9531b7071c734967e9c80acba43cb1a92307dd8f8e9731ad7553dc10da766')
    assert FRESH_SECTION_PROJECTION == 'reader_v2'
    # Only the exact reviewed memo is rendered under this layout too.
    forged = json.loads(json.dumps(result))
    forged['memo']['investment_thesis']['claims'][0]['assertion'] = (
        'The source confirms repeat demand from several paying clinics.')
    with pytest.raises(ValueError):
        renderable_sections(forged, SOURCES, attempts, projection='reader_v2')


def test_profiles_frozen_under_each_layout_replay_that_layout(tmp_path):
    from delivery.investment_memo_stage import frozen_memo_model_profile
    fresh = frozen_memo_model_profile(tmp_path / 'model.json', 'qwen3.5:9b')
    assert fresh['section_projection'] == 'reader_v2'
    for name, layout in (('v1.json', 'reader_v1'), ('old.json', None)):
        saved = {key: value for key, value in fresh.items() if key != 'section_projection'}
        if layout:
            saved['section_projection'] = layout
        (tmp_path / name).write_text(json.dumps(saved))
        again = frozen_memo_model_profile(tmp_path / name, 'qwen3.5:9b')
        assert again == saved and again.get('section_projection') == layout
        assert json.loads((tmp_path / name).read_text()) == saved


def test_reader_v2_editable_memo_and_pdf_carry_the_same_text():
    import re
    from io import BytesIO
    from docx import Document
    from pypdf import PdfReader
    from delivery.inspection import inspect_export_pair
    from delivery.rendering import render_memo, render_memo_pdf
    result, attempts, output = accepted_v2()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    docx, pdf = render_memo('Example Labs', sections), render_memo_pdf('Example Labs', sections)
    pair = inspect_export_pair(docx, 'docx', pdf)
    assert pair['pair_status'] == pair['editable_text_status'] == 'pass'
    normalize = lambda value: re.sub(r'\s+', ' ', value).strip()
    editable = normalize('\n'.join(paragraph.text for paragraph in Document(BytesIO(docx)).paragraphs))
    printed = normalize(' '.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages))
    for heading, body, sources in sections:
        for line in (heading, *body.splitlines(), *sources.splitlines()):
            if line.strip():
                assert normalize(line) in editable
    # Model prose, each claim once, the record as fields and the bibliography reach both files.
    for text, count in ((output['investment_thesis']['analysis'], None), (SECOND, 1), (QUOTE, 1),
                        ('amount: USD 100000; status: unknown.', 1), (SOURCE.url, 1),
                        ('Evidence appendix', 1), ('Sources and retained versions', 1)):
        for rendered in (editable, printed):
            assert normalize(text) in rendered
            if count:
                assert rendered.count(normalize(text)) == count
    assert '{"' not in editable and '{"' not in printed
