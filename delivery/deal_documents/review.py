"""Phase 2 review: independent local reviewer agents, then one targeted revision.

Three agents with separate prompts: a per-section fact checker, a whole-memo
investment-committee critic and a whole-memo compliance reviewer. Every issue
must quote the exact text it objects to; code drops issues whose quote is not
in the draft. Reviews flag problems and questions for counsel; they never
grant legal, financial or release approval.
"""
from __future__ import annotations

import json
import re

from delivery.deal_documents.facts import fact_line
from delivery.deal_documents.llm import ModelResponseError, RecordedModel

FACT_CHECK_SYSTEM = """You are an independent fact checker for an investment memorandum. For each paragraph you receive its text, the exact facts it cites and, for each calculation, what code computed and its result. Go sentence by sentence and check whether every claim follows from those facts. Code has already verified that every number is a cited value or a computed result; your job is meaning: does the sentence describe that number correctly?

Flag only real problems:
- unsupported: a claim not established by the cited facts
- wrong_metric: the paragraph names a different metric than the fact (for example "paying customers" when the fact says "registered users", "revenue" when the fact says "gross volume")
- wrong_period: wrong period or period type (quarter vs year, run-rate vs actual)
- wrong_basis: a projection, target or company claim presented as a reported fact, or third-party data presented without attribution
- overstated: wording stronger than the evidence ("proves", "dominant", "will")
- misread_calculation: a calculation that does not measure what the sentence says

Arithmetic computed by code is correct (for example INR 1,000 Mn at 75 INR/USD is USD 13.33 Mn); never dispute it. Only flag whether the sentence describes the result correctly.

For each issue quote the exact words from the paragraph (copied verbatim, 3-25 words) and give a concrete fix using only figures from the cited facts or the calculations. Do not flag style. If a paragraph is accurate, raise nothing for it: never raise an issue whose fix is to keep the text. Write compact JSON on one line, without indentation."""

CRITIC_SYSTEM = """You are a partner on an investment committee reading a draft investment memorandum before it goes to institutional investors. You have also seen the diligence lead's reconciliation findings.

Raise the issues that would make you send it back:
- vague: a statement with no figure, period or source where one is needed
- padding: sentences that repeat other sections or add no information; say what to cut
- missing_so_what: evidence with no implication for the investment decision
- missing_finding: a material business risk that the memo does not address. Differences between the company's figures are settled with the company and are never written into the memorandum: flag a sentence that relies on a questioned figure, and never ask for a discrepancy to be stated
- unbalanced: positives stated more strongly than the evidence, or risks understated
- structure: points in the wrong section, or the investment summary not reflecting the body

Each issue names the section key, quotes the exact words (verbatim, 3-25 words; use "" only for missing_finding) and states the specific change. Prioritise: at most 4 issues per section, 25 in total. The reconciliation findings include the human reviewer's notes, which were checked against the source pages: never ask for one of those findings to be removed or softened. In `overall`, give two or three sentences: whether the memo is ready for investors and the most important change. Write compact JSON on one line, without indentation."""

COMPLIANCE_SYSTEM = """You are a compliance reviewer for private-company fundraising materials in India, preparing questions for qualified counsel. You do not give legal approval; you flag text and gaps that counsel must resolve.

Review the draft against these areas:
- forward_looking: every forecast, target or run-rate is labelled as a company projection or target with its basis; no assurance or guarantee of returns, growth or valuation.
- attribution: third-party market data names its source and date; company claims are attributed to the company.
- balance: risks and adverse findings have comparable prominence to positives; no misleading comparisons.
- licensing: activities that may need a sector licence or registration are described accurately and not implied to be licensed without evidence.
- private_placement: language must not read as a public offer or general solicitation; Companies Act 2013 section 42 and Rule 14 private placement requirements are for counsel to confirm.
- foreign_investment: if foreign investors are named, FEMA non-debt instrument pricing and reporting are flagged for counsel.
- data_protection: claims about customer data use are consistent with the Digital Personal Data Protection Act 2023.
- disclosures: confidentiality, no-offer and advisor-conflict notices are present or listed as required.

For each area give a status (adequate, needs_change, missing, not_applicable) with a one-sentence reason. Then list specific findings with the section key, the exact quoted words (verbatim, 3-25 words, or "" for something missing) and the required action. Phrase legal points as questions for counsel. Write compact JSON on one line, without indentation."""

AREAS = ['forward_looking', 'attribution', 'balance', 'licensing', 'private_placement', 'foreign_investment',
         'data_protection', 'disclosures']

# Public secondary-source notes gathered 27 October 2026 to ground the reviewer's
# questions. They are prompts for counsel, not verified law or legal advice.
GENERAL_NOTES = """REFERENCE NOTES (public secondary sources, 27 October 2026; counsel must verify current law):
- Companies Act 2013 s.42 / Companies (PAS) Rules 2014 Rule 14: private placement offers go only to persons identified in advance, at most 200 persons per financial year per kind of security (QIBs and ESOP employees excluded), via a serially numbered PAS-4 offer letter, with a special resolution and no public advertisement; breaches risk deemed public offer treatment.
- FEMA non-debt instrument rules: issues to non-residents need pricing at or above fair value and reporting (for example form FC-GPR); counsel to confirm for named foreign investors.
- Digital Personal Data Protection Act 2023 and DPDP Rules 2025: phased commencement; claims about using customer data for pricing need a lawful basis."""
# Sector notes join the general ones only when a company's own text matches. Add a sector by adding an entry; no code depends on one.
SECTOR_NOTES = [
    (re.compile(r'\b(insurance|insurer|reinsur\w*|underwrit\w*|irdai)\b', re.IGNORECASE),
     """- IRDAI point-of-sales person (POSP) guidelines: individuals selling insurance at point of sale must be trained and certified through an insurer or intermediary and are limited to simple pre-underwritten products (for example motor, travel, personal accident); records of POS business must be kept.
- Managing general agents: MGAs became a recognised insurance-intermediary category only through the Insurance Act amendment effective 5 February 2026; sources indicate IRDAI domestic (DTA) MGA regulations may not yet be in force. Before that, Indian intermediaries could not underwrite or accept risk for insurers. Materials describing an "MGA model" therefore raise a licensing question for counsel."""),
]


def reference_notes(text):
    """The general notes, plus any sector's notes that `text` (the company's own facts or draft) calls for."""
    return '\n'.join([GENERAL_NOTES] + [notes for pattern, notes in SECTOR_NOTES if pattern.search(text)])


def _paragraphs(section):
    return [paragraph['text'] for paragraph in section['paragraphs']]


def _quote_ok(quote, texts):
    quote = ' '.join(quote.split())
    return bool(quote) and any(quote in ' '.join(text.split()) for text in texts)


def fact_check(model: RecordedModel, section, index, human_notes=''):
    """`human_notes` are the human reviewer's findings, checked against the source pages; a sentence stating
    one is supported even when the paragraph's own citations do not show all of it."""
    if not section['paragraphs']:
        return []
    blocks = []
    if human_notes:
        blocks += ['HUMAN REVIEW FINDINGS (checked against the source pages; never ask for these to be removed or '
                   'contradicted, only for a sentence that misstates one to be corrected):', human_notes, '']
    for number, paragraph in enumerate(section['paragraphs'], 1):
        blocks.append(f'PARAGRAPH {number}: {paragraph["text"]}')
        blocks += ['  cites: ' + fact_line(index[fact_id]) for fact_id in paragraph['cites'] if fact_id in index]
        for calc_id in paragraph.get('calculations_used', []):
            result = section['results'].get(calc_id)
            if isinstance(result, dict):
                blocks.append(f'  calculation computed by code: {result["label"]} ({result["kind"]}) = {result["text"]}'
                              + (' [uses projections]' if result['projection'] else ''))
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['issues'],
              'properties': {'issues': {'type': 'array', 'maxItems': 12, 'items': {
                  'type': 'object', 'additionalProperties': False, 'required': ['paragraph', 'type', 'quote', 'problem', 'fix'],
                  'properties': {'paragraph': {'type': 'integer', 'minimum': 1, 'maximum': len(section['paragraphs'])},
                                 'type': {'type': 'string', 'enum': ['unsupported', 'wrong_metric', 'wrong_period', 'wrong_basis',
                                                                     'overstated', 'misread_calculation']},
                                 'quote': {'type': 'string', 'maxLength': 240}, 'problem': {'type': 'string', 'maxLength': 300},
                                 'fix': {'type': 'string', 'maxLength': 300}}}}}}
    result = model.json(f'factcheck-{section["section"]}', 'check', FACT_CHECK_SYSTEM, '\n'.join(blocks), schema)
    texts = _paragraphs(section)
    return [{**issue, 'reviewer': 'fact_checker', 'section': section['section'],
             'quote_verified': _quote_ok(issue['quote'], [texts[issue['paragraph'] - 1]])} for issue in result['issues']]


def memo_text(sections):
    parts = []
    for section in sections:
        parts.append(f'### [{section["section"]}] {section["title"]}')
        parts += [paragraph['text'] for paragraph in section['paragraphs']]
    return '\n\n'.join(parts)


def critic(model: RecordedModel, sections, findings_text):
    keys = [section['section'] for section in sections]
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['issues', 'overall'],
              'properties': {'overall': {'type': 'string', 'maxLength': 600},
                             'issues': {'type': 'array', 'maxItems': 25, 'items': {
                                 'type': 'object', 'additionalProperties': False, 'required': ['section', 'type', 'quote', 'change'],
                                 'properties': {'section': {'type': 'string', 'enum': keys},
                                                'type': {'type': 'string', 'enum': ['vague', 'padding', 'missing_so_what',
                                                                                    'missing_finding', 'unbalanced', 'structure']},
                                                'quote': {'type': 'string', 'maxLength': 240},
                                                'change': {'type': 'string', 'maxLength': 400}}}}}}
    prompt = f'RECONCILIATION FINDINGS:\n{findings_text}\n\nDRAFT MEMORANDUM:\n{memo_text(sections)}'
    result = _with_fallback(model, 'critic', CRITIC_SYSTEM, prompt, schema)
    by_key = {section['section']: _paragraphs(section) for section in sections}
    issues = [{**issue, 'reviewer': 'ic_critic',
               'quote_verified': issue['type'] == 'missing_finding' or _quote_ok(issue['quote'], by_key[issue['section']])}
              for issue in result['issues']]
    return issues, result['overall']


DECK_CRITIC_SYSTEM = """You are a managing director at an investment bank, with a partner from a growth venture fund beside you, reviewing a pitch deck before it goes to institutional investors. You have the approved memorandum it summarises. Judge the deck the way an investor reads it: the headlines in sequence, then the visuals, then the bullets.

Raise the issues that would make you send it back:
- storyline: read in order, the headlines do not build the investment case, or a slide is out of place
- weak_headline: the headline is a label or does not state what the investor should conclude
- headline_unsupported: the headline claims more than the slide's evidence shows
- missing_key_point: a material point of the memorandum (a key figure, risk or finding) is missing from the slide where it belongs
- clutter: a bullet repeats another slide or adds nothing an investor would act on; say what to cut
- unbalanced: positives stated more strongly than in the memorandum, or risks softened
- visual: the wrong table, rows or chart for the slide's point, or a visual that should be added or removed

Each issue names the slide key, quotes the exact words (verbatim, 3-25 words; use "" only for storyline, missing_key_point or visual) and states the specific change, using only what the memorandum supports. Prioritise: at most 3 issues per slide, 20 in total. In `overall`, give two or three sentences: whether this deck would earn a first meeting and the most important change. Write compact JSON on one line, without indentation."""


def deck_critic(model: RecordedModel, slides, deck_text, memo):
    keys = [slide['section'] for slide in slides]
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['issues', 'overall'],
              'properties': {'overall': {'type': 'string', 'maxLength': 600},
                             'issues': {'type': 'array', 'maxItems': 20, 'items': {
                                 'type': 'object', 'additionalProperties': False, 'required': ['section', 'type', 'quote', 'change'],
                                 'properties': {'section': {'type': 'string', 'enum': keys},
                                                'type': {'type': 'string', 'enum': ['storyline', 'weak_headline', 'headline_unsupported',
                                                                                    'missing_key_point', 'clutter', 'unbalanced', 'visual']},
                                                'quote': {'type': 'string', 'maxLength': 240},
                                                'change': {'type': 'string', 'maxLength': 400}}}}}}
    result = _with_fallback(model, 'deck-critic', DECK_CRITIC_SYSTEM, f'APPROVED MEMORANDUM:\n{memo}\n\nDRAFT DECK:\n{deck_text}', schema)
    by_key = {slide['section']: _paragraphs(slide) for slide in slides}
    issues = [{**issue, 'reviewer': 'deck_critic',
               'quote_verified': (not issue['quote'] and issue['type'] in ('storyline', 'missing_key_point', 'visual'))
               or _quote_ok(issue['quote'], by_key[issue['section']])} for issue in result['issues']]
    return issues, result['overall']


def _with_fallback(model, name, system, prompt, schema):
    """Reasoning review first; if it fails (for example a degenerate finishing loop), answer once directly."""
    try:
        return model.json(name, 'review', system, prompt, schema)
    except ModelResponseError:
        settings = {'think': False, 'options': {'temperature': 0.3, 'top_p': 0.8, 'top_k': 20, 'num_ctx': 32768,
                                                'num_predict': 6000, 'repeat_penalty': 1.05}}
        return model.json(f'{name}-direct', 'review', system, prompt, schema, settings=settings)


def compliance(model: RecordedModel, sections, name='compliance', notices=(), document='MEMORANDUM'):
    """`notices` are the (title, text) pairs code prints at the front of the finished document."""
    keys = [section['section'] for section in sections] + ['whole_document']
    area = {'type': 'object', 'additionalProperties': False, 'required': ['area', 'status', 'reason'],
            'properties': {'area': {'type': 'string', 'enum': AREAS},
                           'status': {'type': 'string', 'enum': ['adequate', 'needs_change', 'missing', 'not_applicable']},
                           'reason': {'type': 'string', 'maxLength': 300}}}
    finding = {'type': 'object', 'additionalProperties': False, 'required': ['area', 'section', 'quote', 'action'],
               'properties': {'area': {'type': 'string', 'enum': AREAS}, 'section': {'type': 'string', 'enum': keys},
                              'quote': {'type': 'string', 'maxLength': 240}, 'action': {'type': 'string', 'maxLength': 400}}}
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['areas', 'findings'],
              'properties': {'areas': {'type': 'array', 'minItems': len(AREAS), 'maxItems': len(AREAS), 'items': area},
                             'findings': {'type': 'array', 'maxItems': 25, 'items': finding}}}
    printed = ''
    if notices:
        printed = (f'\n\nNOTICES CODE PRINTS AT THE FRONT OF THE FINISHED {document} (the body must not repeat or rewrite them; '
                   'judge them under disclosures):\n' + '\n'.join(f'- {title}: {text}' for title, text in notices))
    result = _with_fallback(model, name, COMPLIANCE_SYSTEM,
                            reference_notes(memo_text(sections)) + printed + f'\n\nDRAFT {document}:\n' + memo_text(sections), schema)
    by_key = {section['section']: _paragraphs(section) for section in sections}
    findings = [{**item, 'reviewer': 'compliance',
                 'quote_verified': not item['quote'] or _quote_ok(item['quote'], by_key.get(item['section'], sum(by_key.values(), [])))}
                for item in result['findings']]
    return result['areas'], findings


def review_memo(model: RecordedModel, sections, fact_base, findings_text):
    index = {fact['id']: fact for fact in fact_base['facts'] + fact_base['workbook_cells']}
    issues, failures = [], []
    for section in sections:
        try:
            issues += fact_check(model, section, index)
        except ModelResponseError as exc:
            failures.append(f'fact check {section["section"]}: {exc}')
    overall, areas = '', []
    try:
        critic_issues, overall = critic(model, sections, findings_text)
        issues += critic_issues
    except ModelResponseError as exc:
        failures.append(f'critic: {exc}')
    try:
        areas, compliance_findings = compliance(model, sections)
        issues += compliance_findings
    except ModelResponseError as exc:
        failures.append(f'compliance: {exc}')
    return {'issues': issues, 'overall': overall, 'compliance_areas': areas, 'failures': failures}


def known_numbers(index, sections):
    """Every number a reviewer may legitimately propose: fact values and statements, and code-computed results."""
    from delivery.deal_documents.facts import numbers_in
    from delivery.deal_documents.memo import result_numbers
    numbers = [n for fact in index.values() for n in numbers_in(' '.join([fact['value'], fact['period'], fact['statement']]))]
    return numbers + [n for section in sections for n in result_numbers(section.get('results', {}))] + numbers_in(reference_notes(json.dumps(sections, default=str)))


def proposes_unknown_number(issue, known):
    """True when a reviewer's change contains a figure that is in no fact and no calculation (it would inject an error)."""
    from delivery.deal_documents.facts import number_present, numbers_in
    change = ' '.join(str(issue.get(key) or '') for key in ('fix', 'change', 'action'))
    return any(not number_present(value, known) for value in numbers_in(change))


def notes_for(section_key, review, known=None):
    notes = []
    for issue in review['issues']:
        if issue.get('section') != section_key or not issue.get('quote_verified'):
            continue
        if known is not None and proposes_unknown_number(issue, known):
            continue
        quote = f'"{issue["quote"]}" — ' if issue.get('quote') else ''
        action = issue.get('fix') or issue.get('change') or issue.get('action')
        problem = issue.get('problem', issue.get('type', issue.get('area', '')))
        notes.append(f'- [{issue["reviewer"]}] {quote}{problem}. Change: {action}')
    return '\n'.join(notes)
