"""Deterministic compliance gate for the investment memorandum (code-owned, not model judgement).

It complements the local compliance reviewer agent. Code scans every sentence
for assurance and public-offer language, confirms that forward-looking figures
are labelled (the sentence checks in `semantics`), measures how old the
information is, and checks the memo against a disclosure checklist modelled on
the section headings of offer documents. Jurisdiction-specific draft legends
and disclosure schedules use explicit issuer incorporation evidence. Applicable
placement rules, sector licensing and foreign investment remain questions for
counsel; evidence supplied is never a finding of legal compliance.

Nothing here is legal advice or a legal sign-off. External release requires a
recorded sign-off by a named, qualified person (see runs.APPROVALS), and every
`fail` item must be fixed or explicitly waived in that sign-off.
"""
from __future__ import annotations

import datetime
import re

ASSURANCE = re.compile(r'\b(guarantee\w*|assured|assurance of|risk[- ]free|no risk|certain to|certainly will|will certainly|'
                       r'sure[- ]shot|safe investment|cannot lose|multi-?bagger|definitely|promise[sd]? (?:a |an )?return\w*|'
                       r'fixed return\w*|returns? of \d+\s*%)\b', re.IGNORECASE)
# "will reach" is an assurance unless the same sentence attributes it as a projection.
UNATTRIBUTED_FUTURE = re.compile(r'\bwill (?:double|triple|deliver|achieve|generate|reach|grow|become|capture|dominate)\b', re.IGNORECASE)
PUBLIC_OFFER = re.compile(r'\b(public offer\w*|open to (?:all|the public|everyone)|invit\w+ the public|subscribe now|apply now|'
                          r'limited[- ]period offer|first come,? first served|public advertisement|advertis\w* (?:this|the) '
                          r'(?:offer|issue|raise|round)|general solicitation|anyone can invest)\b',
                          re.IGNORECASE)

# (key, heading, memo sections that satisfy it, question when absent)
DISCLOSURES = [
    ('risk_factors', 'Risk factors', ['risks'], None),
    ('forward_looking', 'Forward-looking statements notice', ['_notice'], None),
    ('business', 'Business overview', ['company', 'business_model'], None),
    ('industry', 'Industry and market', ['market'], None),
    ('management', 'Management', ['team'], None),
    ('capital_structure', 'Capital structure and shareholding', ['capital'], None),
    ('financial_information', 'Financial information', ['historical'], None),
    ('approvals', 'Government and other approvals (licences)', ['regulatory'], None),
    ('use_of_proceeds', 'Objects of the issue (use of proceeds)', [],
     'How much is being raised, on what instrument and terms, and how will the proceeds be used?'),
    ('litigation', 'Outstanding litigation and material developments', [],
     'Is there any outstanding litigation, regulatory action or tax demand against the company, its promoters or directors, '
     'and any material development since the latest reported period?'),
    ('related_parties', 'Related-party transactions', [],
     'List all related-party transactions in the last three financial years and the current year, with amounts and approvals.'),
    ('promoters', 'Promoters and promoter group', ['team', 'capital'], None),
]

INDIA_RULE = 'Companies Act 2013 section 42; Companies (Prospectus and Allotment of Securities) Rules 2014, Rule 14 and Form PAS-4'
US_RULE = 'Securities Act of 1933, Regulation D'
JURISDICTION_METRICS = ('issuer jurisdiction', 'jurisdiction of incorporation', 'country of incorporation',
                        'place of incorporation', 'incorporation', 'jurisdiction')
ROUTE_METRICS = ('offering exemption', 'offering route', 'placement exemption', 'regulation d exemption')
MISSING = re.compile(r'^(?:unknown|outstanding|pending|tbd|n/?a|unconfirmed|unavailable)[.!]?$|'
                     r'\b(?:not (?:supplied|provided|available|confirmed)|to be (?:confirmed|provided|prepared)|'
                     r'will be (?:provided|supplied))\b', re.I)

# Each row requires its own labelled evidence, not merely a fact on the same topic.
COMMON_REQUIREMENTS = [
    ('identity', 'Issuer identity and registered office', ('issuer identity', 'registered office'), 'Company secretary'),
    ('business', 'Business overview', ('business overview', 'business description'), 'Management'),
    ('management', 'Directors and management', ('directors and management', 'management biographies'), 'Company secretary'),
    ('risks', 'Material risk factors', ('risk factors', 'material risks'), 'Management and counsel'),
    ('capital', 'Capital structure and shareholding', ('capital structure', 'capital structure and shareholding'), 'Company secretary'),
    ('terms', 'Amount, instrument and security rights', ('offering terms', 'transaction terms'), 'Management and counsel'),
    ('pricing', 'Pricing basis and valuation report', ('pricing basis', 'valuation report'), 'Finance and valuer'),
    ('proceeds', 'Objects and use of proceeds', ('use of proceeds', 'objects of the issue'), 'Finance'),
    ('financials', 'Financial statements and audit qualifications', ('financial statements', 'audited financial statements'), 'Finance and auditor'),
    ('litigation', 'Litigation and regulatory actions', ('litigation and regulatory actions', 'outstanding litigation'), 'Company counsel'),
    ('related_parties', 'Related-party dealings and conflicts', ('related-party transactions', 'related party transactions'), 'Finance and counsel'),
    ('developments', 'Material developments since reporting date', ('material developments', 'subsequent events'), 'Management'),
    ('approvals', 'Licences and regulatory approvals', ('licences and approvals', 'regulatory approvals'), 'Company counsel'),
    ('fees', 'Preparer fees, interests and registration', ('preparer fees and conflicts', 'intermediary role'), 'Preparer and counsel'),
]
INDIA_REQUIREMENTS = [
    ('pas4', 'Serially numbered PAS-4 offer cum application', ('pas-4 offer letter', 'private placement offer letter'), 'Company secretary'),
    ('recipients', 'Identified persons; annual limit by security kind', ('identified persons register', 'private placement recipients'), 'Company secretary'),
    ('advertising', 'No public advertisement or public marketing', ('private placement distribution controls', 'no public advertisement'), 'Management and counsel'),
    ('resolutions', 'Board and shareholder approvals; filing evidence', ('private placement approvals', 'placement resolutions'), 'Company secretary'),
    ('interests', 'Director interests, remuneration and contributions', ('director interests and remuneration',), 'Company secretary'),
    ('defaults', 'Borrowing, deposit and statutory defaults', ('defaults disclosure', 'borrowing and statutory defaults'), 'Finance and auditor'),
    ('fraud', 'Fraud, inquiries and penalties; required lookback', ('fraud inquiries and penalties',), 'Company counsel'),
    ('pas4_financials', 'PAS-4 financial history, dividends and ratios', ('pas-4 financial disclosures',), 'Finance and auditor'),
    ('audit', 'Auditor reservations and responses; five-year history', ('auditor reservations and responses',), 'Finance and auditor'),
    ('accounting', 'Accounting policy changes; three-year history', ('accounting policy changes',), 'Finance and auditor'),
    ('contact', 'Nodal officer and offer contact details', ('private placement contact',), 'Company secretary'),
    ('security', 'Security, guarantees and repayment terms', ('security and guarantees',), 'Finance and counsel'),
    ('declaration', 'PAS-4 declarations and authorised signature', ('pas-4 declarations',), 'Directors and counsel'),
    ('allotment', 'Payment, allotment, refund and PAS-3 reporting', ('allotment and reporting plan',), 'Company secretary'),
    ('sebi', 'SEBI applicability: listing, instrument, intermediary', ('sebi applicability',), 'Securities counsel'),
    ('fema', 'FEMA: investor residency, route, caps, pricing, reporting', ('fema assessment', 'foreign investment assessment'), 'Counsel and authorised dealer'),
]
US_REQUIREMENTS = [
    ('exemption', 'Counsel-confirmed exemption and offering route', ROUTE_METRICS, 'US securities counsel'),
    ('accredited', 'Accredited status and purchaser eligibility', ('investor eligibility', 'accredited investor assessment'), 'Issuer and US counsel'),
    ('solicitation', 'Solicitation policy for the selected exemption', ('solicitation policy',), 'Issuer and US counsel'),
    ('restricted', 'Restricted securities and transfer limitations', ('transfer restrictions', 'restricted securities'), 'US securities counsel'),
    ('bad_actors', 'Bad actor disqualification checks', ('bad actor checks',), 'US securities counsel'),
    ('filings', 'Form D and applicable state notices and fees', ('form d and state filings',), 'US securities counsel'),
]


def _label(value):
    return ' '.join(str(value or '').casefold().strip().split())


def _evidence(fact_base):
    return [fact for fact in [*fact_base.get('facts', []), *fact_base.get('workbook_cells', [])]
            if all(fact.get(key) for key in ('id', 'document', 'location', 'statement'))
            and not any(fact.get(key) for key in ('ambiguity', 'ocr_only', 'cell_error'))
            and fact.get('basis') not in ('projection', 'target', 'definition')
            and fact.get('topic') not in ('competition', 'market')
            and _label(fact.get('entity')) in ('', 'issuer', 'company')
            and _label(fact.get('segment')) in ('', 'issuer', 'company', 'total')
            and not MISSING.search(fact['statement'].split(':', 1)[-1].strip())]


def _citation(fact):
    return f'[{fact["id"]}] {fact["document"]}, {fact["location"]}'


def jurisdiction(fact_base):
    """Explicit issuer incorporation evidence only; currencies and markets prove nothing."""
    evidence, countries = [], set()
    for fact in _evidence(fact_base):
        metric = _label(fact.get('metric'))
        text = fact['statement']
        if metric == 'jurisdiction' and fact.get('topic') != 'company':
            continue
        if metric not in JURISDICTION_METRICS:
            if fact.get('topic') not in ('company', 'regulatory') or not re.search(
                    r'\b(?:the (?:issuer|company)|issuer|company) (?:is |was )?incorporated (?:in|under)\b', text, re.I):
                continue
        else:
            text = text.split(':', 1)[-1]
        evidence.append(fact)
        found = set()
        if re.search(r'\b(?:not|may|proposed|considering|or)\b', text, re.I):
            countries.add('unknown')
            continue
        incorporation = re.search(r'\bincorporated (?:in|under)\s+(?:the laws of\s+)?(.+)', text, re.I)
        if incorporation:
            text = incorporation[1]
        text = re.split(r'\b(?:with|but|which|whose)\b|\band (?=operates|serves|sells|has|maintains)\b|[;\n]',
                        text, maxsplit=1, flags=re.I)[0].strip()
        if re.search(r'\band\b', text, re.I):
            countries.add('unknown')
            continue
        if not re.match(r'^(?:the\s+)?(?:Republic of India|India|Indian|Companies Act,?\s+2013|'
                        r'United States|U\.?S\.?A?\.?|Delaware)\b', text, re.I):
            countries.add('unknown')
            continue
        if re.search(r'\b(?:India|Indian|Companies Act,?\s+2013)\b', text, re.I):
            found.add('IN')
        if re.search(r'\b(?:United States(?: of America)?|U\.?S\.?A?\.?|Delaware)\b', text, re.I):
            found.add('US')
        countries.update(found or {'unknown'})
    country = next(iter(countries)) if len(countries) == 1 else 'unknown'
    return {'country': country, 'evidence': evidence,
            'question': '' if country in ('IN', 'US') else
            'Ask the company secretary and counsel: provide the issuer incorporation jurisdiction and certificate; '
            'resolve any conflicting evidence and identify applicable offering laws.'}


def offering_route(fact_base):
    found, evidence = set(), []
    for fact in _evidence(fact_base):
        if _label(fact.get('metric')) in ROUTE_METRICS:
            evidence.append(fact)
            routes = re.findall(r'\b506\s*\(([bc])\)', fact['statement'], re.I)
            found.update(route.lower() for route in routes)
            if len(routes) != 1 or re.search(r'\b(?:not|or|considering|proposed|may|alternative)\b', fact['statement'], re.I):
                found.add('unknown')
    return (next(iter(found)) if len(found) == 1 else 'unknown'), evidence


def regulatory_notice(fact_base):
    chosen = jurisdiction(fact_base)
    prefix = 'Draft legend for counsel review; no legal compliance conclusion. '
    if chosen['country'] == 'IN':
        text = (f'{INDIA_RULE}: any offer needs a separate PAS-4 offer cum application to identified persons. '
                'Counsel must confirm the limit of 200 persons per financial year for each kind of security, '
                'excluding qualified institutional buyers and employees offered securities under employee stock option schemes; confirm applicable exceptions. '
                'No public advertisement or public marketing is permitted. Confirm SEBI rules where applicable; '
                'for non-resident investors, assess FEMA and the Foreign Exchange Management (Non-debt Instruments) Rules 2019, '
                'entry route, caps, pricing and reporting; debt instruments need their applicable FEMA framework.')
    elif chosen['country'] == 'US':
        route, _ = offering_route(fact_base)
        text = f'{US_RULE}: '
        if route == 'b':
            text += ('the source identifies Rule 506(b), subject to counsel confirmation. No general solicitation or '
                     'general advertising; confirm accredited investor status and any permitted sophisticated '
                     'non-accredited purchasers and their Rule 502(b) information rights. ')
        elif route == 'c':
            text += ('the source identifies Rule 506(c), subject to counsel confirmation. All purchasers must be '
                     'accredited investors and the issuer must take reasonable steps to verify that status. '
                     'General solicitation is permitted only subject to the exemption conditions. ')
        else:
            text += ('counsel must select Rule 506(b) or Rule 506(c); no route is established. Rule 506(b) prohibits '
                     'general solicitation; Rule 506(c) permits it conditionally, requires all purchasers to be '
                     'accredited investors and reasonable steps to verify that status. ')
        text += 'Securities are restricted; resale requires registration or an available exemption. Confirm filings and disqualification checks.'
    else:
        text = chosen['question'] + ' Do not select a private-placement exemption until counsel resolves this.'
    return ('Regulatory legend — draft for counsel', prefix + text)


def disclosure_checklist(fact_base):
    """Evidence availability and named suppliers, never a legal sufficiency test."""
    chosen = jurisdiction(fact_base)
    facts = _evidence(fact_base)
    rows = [{'key': 'jurisdiction', 'title': 'Issuer incorporation jurisdiction',
             'status': 'supplied' if chosen['country'] in ('IN', 'US') else 'outstanding',
             'detail': 'Supplied evidence; counsel must confirm applicable laws.' if chosen['country'] in ('IN', 'US') else chosen['question'],
             'evidence': chosen['evidence'], 'supplier': 'Company secretary and counsel', 'rule': ''}]
    requirements = [(item, 'Disclosure diligence') for item in COMMON_REQUIREMENTS]
    if chosen['country'] == 'IN':
        requirements += [(item, INDIA_RULE if item[0] not in ('sebi', 'fema') else
                          'SEBI rules, if applicable' if item[0] == 'sebi' else 'FEMA; applicable instrument rules')
                         for item in INDIA_REQUIREMENTS]
    elif chosen['country'] == 'US':
        requirements += [(item, US_RULE) for item in US_REQUIREMENTS]
        route, _ = offering_route(fact_base)
        if route != 'c':
            requirements.append((('information_rights', 'Rule 502(b) information and questions; if non-accredited purchasers',
                                  ('rule 502(b) disclosures',), 'Issuer, auditor and US counsel'), US_RULE))
        if route != 'b':
            requirements.append((('verification', 'If Rule 506(c): reasonable steps to verify accredited status',
                                  ('accredited investor verification',), 'Issuer and US counsel'), US_RULE + ', Rule 506(c)'))
    else:
        requirements.append((('applicability', 'Applicable placement rules and required disclosures', (),
                              'Company counsel'), 'Jurisdiction unresolved'))
    for (key, title, metrics, supplier), rule in requirements:
        evidence = [fact for fact in facts if _label(fact.get('metric')) in metrics]
        supplied = bool(evidence)
        if key == 'exemption' and offering_route(fact_base)[0] not in ('b', 'c'):
            supplied = False
        rows.append({'key': key, 'title': title, 'status': 'supplied' if supplied else 'outstanding',
                     'detail': 'Supplied evidence; counsel review of completeness required.' if supplied else
                     'Outstanding: supply the disclosure or a reasoned applicability assessment.',
                     'evidence': evidence, 'supplier': supplier, 'rule': rule})
    return rows


def counsel_questions(fact_base):
    chosen = jurisdiction(fact_base)
    questions = [('private_placement', regulatory_notice(fact_base)[1]),
                 ('sector_licensing', 'Sector regulator: Confirm the licences and approvals required for each activity and their holders.'),
                 ('intermediary_role', 'Role of the preparer: Confirm applicable registration requirements, conflicts and fees.')]
    if chosen['country'] == 'IN':
        questions += [('foreign_investment', 'FEMA: establish investor residency and the applicable instrument framework, '
                       'entry route, caps, pricing, payment and reporting.'),
                      ('sebi_applicability', 'SEBI: establish listing status, security type and intermediary roles before deciding which rules apply.')]
        questions.append(('data_protection', 'Digital Personal Data Protection Act 2023: confirm the applicable obligations, '
                          'lawful basis and notices for the uses of personal data described.'))
    return questions


def latest_reported_period(fact_base, fiscal_year_end_month=3):
    """(label, end_month) of the latest historical period in the fact base, or (None, None)."""
    best = (None, None)
    for fact in fact_base['facts']:
        if fact.get('basis') != 'historical':
            continue
        from delivery.deal_documents.semantics import period_of
        parsed = period_of(fact.get('period'), fiscal_year_end_month)
        if parsed and parsed[0] in ('quarter', 'year', 'month') and (best[1] is None or parsed[1] > best[1]):
            best = (fact['period'], parsed[1])
    return best


def information_age(fact_base, today=None, fiscal_year_end_month=3):
    """(label of the latest reported period, whole months between its end and today); (None, None) when unknown."""
    today = today or datetime.date.today()
    label, end = latest_reported_period(fact_base, fiscal_year_end_month)
    return (label, today.year * 12 + today.month - end) if end else (None, None)


def _month_name(month_index):
    year, month = divmod(month_index - 1, 12)
    return datetime.date(year, month + 1, 1).strftime('%B %Y')


def notices(company, fact_base, today=None, fiscal_year_end_month=3):
    """Notices printed at the front of the memorandum, in this order."""
    today = today or datetime.date.today()
    from delivery.deal_documents.public_sources import public_basis
    basis = public_basis(fact_base) or ('Prepared from materials supplied by the company. They have not been audited or '
                                      'independently verified, and no representation is made as to their accuracy or completeness.')
    label, end = latest_reported_period(fact_base, fiscal_year_end_month)
    age = (today.year * 12 + today.month - end) if end else None
    dated = (f'The latest reported period in the materials is {label} (ending {_month_name(end)}), {age} months before this draft. '
             'Figures after that period are company projections. Current financial statements must be obtained before any '
             'investment decision.') if end else 'The materials do not state a reported period; the date of the information is unknown.'
    legend_title, legend = regulatory_notice(fact_base)
    return [
        ('Confidentiality and restricted distribution',
         f'This memorandum about {company} is confidential and is provided only to the named recipient for evaluating a possible '
         'private investment. It must not be copied, forwarded or disclosed. It is not an offer or invitation to the public or '
         'to any person to subscribe for securities, and it is not a prospectus or a private placement offer letter. Any offer '
         'requires separate offering documents and counsel confirmation of the applicable exemption and distribution restrictions.'),
        ('Basis of preparation and date of information',
         basis + ' ' + dated),
        ('Forward-looking statements',
         'Projections, targets and run rates are the company\'s forward-looking statements. They depend on assumptions that may '
         'not hold, actual results may differ materially, and nothing in this memorandum is a promise or guarantee of future '
         'performance, returns or valuation.'),
        (legend_title,
         'This memorandum is not investment, legal, tax or regulatory advice. Recipients should make their own assessment with '
         'their own advisers. Any fee or interest of the preparer in the transaction must be disclosed to recipients before '
         'any offer. ' + legend),
    ]


def assurance_language(sentence):
    from delivery.deal_documents.semantics import PROJECTION_WORDS
    return ASSURANCE.search(sentence) or (UNATTRIBUTED_FUTURE.search(sentence) and not PROJECTION_WORDS.search(sentence))


def assess(sections, fact_base, model_areas=(), model_findings=(), today=None, fiscal_year_end_month=3, open_questions=()):
    """Checklist items with status pass | fail | counsel and the blockers to external release.

    The local compliance reviewer's areas and quoted findings are added as counsel items: they are model
    judgement, so they inform counsel but never pass or block release on their own.
    """
    from delivery.deal_documents.semantics import sentences
    today = today or datetime.date.today()
    checks = []
    texts = [(section['section'], paragraph['text']) for section in sections for paragraph in section['paragraphs']]
    def scan(name, title, test, why):
        hits = [f'[{key}] "{sentence.strip()[:160]}"' for key, text in texts for sentence in sentences(text) if test(sentence)]
        checks.append({'key': name, 'title': title, 'status': 'fail' if hits else 'pass', 'detail': why if hits else 'None found',
                       'evidence': hits[:10]})
    scan('assurance_language', 'No assurance or guarantee of returns, growth or valuation', assurance_language,
         'Remove assurance language; forward-looking figures must be stated as company projections.')
    # The memorandum does not narrate questioned figures, so nothing can leave until the company has settled them.
    unsettled = [question['text'] for question in open_questions if question['severity'] == 'high' and not question.get('answer')]
    checks.append({'key': 'figures_under_confirmation', 'title': 'Figures and definitions settled with the company', 'status': 'fail' if unsettled else 'pass',
                   'detail': f'{len(unsettled)} high-severity questions are unanswered.' if unsettled else 'None open', 'evidence': unsettled[:10]})
    scan('public_offer_language', 'No public-offer or solicitation language', PUBLIC_OFFER.search,
         'Remove wording that reads as an offer to the public.')
    unresolved = [f'[{section["section"]}] {problem}' for section in sections for problem in section.get('problems', [])]
    checks.append({'key': 'evidence_and_labelling', 'title': 'Every figure cited, and every projection, target, run rate and '
                   'third-party figure labelled in its sentence', 'status': 'fail' if unresolved else 'pass',
                   'detail': f'{len(unresolved)} unresolved validation problems' if unresolved else 'All sections passed code validation',
                   'evidence': unresolved[:15]})
    label, end = latest_reported_period(fact_base, fiscal_year_end_month)
    age = (today.year * 12 + today.month - end) if end else None
    # Old information is disclosed by the dated notice and raised with the company and counsel; it does not block release.
    checks.append({'key': 'information_date', 'title': 'Information is current (latest reported period within 12 months)',
                   'status': 'counsel' if age is None or age > 12 else 'pass',
                   'detail': (f'Latest reported period {label} ended {age} months ago; the documents state this date in their notices. '
                              'Ask the company for anything newer.') if age is not None and age > 12
                   else (f'Latest reported period {label}' if label else 'No reported period found'), 'evidence': []})
    present = {section['section'] for section in sections if section['paragraphs']} | {'_notice'}
    for key, heading, satisfied_by, question in DISCLOSURES:
        if satisfied_by and set(satisfied_by) & present:
            checks.append({'key': f'disclosure_{key}', 'title': f'Disclosure: {heading}', 'status': 'pass',
                           'detail': 'Covered in ' + ', '.join(s for s in satisfied_by if s in present), 'evidence': []})
        else:
            checks.append({'key': f'disclosure_{key}', 'title': f'Disclosure: {heading}', 'status': 'fail',
                           'detail': question or 'Section missing', 'evidence': []})
    for key, question in counsel_questions(fact_base):
        checks.append({'key': f'counsel_{key}', 'title': question.split(':')[0], 'status': 'counsel', 'detail': question, 'evidence': []})
    for item in disclosure_checklist(fact_base):
        checks.append({'key': 'schedule_' + item['key'], 'title': item['title'],
                       'status': 'counsel' if item['status'] == 'supplied' else 'fail',
                       'detail': item['detail'] + ' Supplier: ' + item['supplier'] + '.',
                       'evidence': [_citation(fact) for fact in item['evidence']]})
    for area in model_areas:
        if area['status'] in ('needs_change', 'missing'):
            evidence = [f'[{item["section"]}] "{item["quote"]}" — {item["action"]}' if item.get('quote') else f'[{item["section"]}] {item["action"]}'
                        for item in model_findings if item.get('area') == area['area'] and (item.get('quote_verified') or not item.get('quote'))]
            checks.append({'key': f'reviewer_{area["area"]}', 'title': f'Local compliance reviewer: {area["area"].replace("_", " ")}',
                           'status': 'counsel', 'detail': f'{area["status"].replace("_", " ")} — {area["reason"]}', 'evidence': evidence[:8]})
    return {'checks': checks, 'blockers': [check['key'] for check in checks if check['status'] == 'fail'],
            'counsel_questions': [check['key'] for check in checks if check['status'] == 'counsel'],
            'assessed_on': today.isoformat()}


def markdown(assessment, document='draft investment memorandum'):
    icon = {'pass': 'PASS', 'fail': 'FAIL', 'counsel': 'COUNSEL'}
    lines = [f'# Compliance gate — {document}', '',
             'Code-run checks plus questions for qualified counsel. This is not legal advice or a legal sign-off. External release '
             'requires a recorded sign-off by a named qualified reviewer that resolves or waives every FAIL item.', '']
    for check in assessment['checks']:
        lines.append(f'- **{icon[check["status"]]}** {check["title"]}: {check["detail"]}')
        lines += [f'  - {item}' for item in check['evidence']]
    return '\n'.join(lines)
