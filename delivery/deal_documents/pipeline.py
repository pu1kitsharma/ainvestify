"""Phase execution with tracked, cached steps (used by the worker service and the operator CLI).

facts: extract each page/sheet -> choose summary sheets -> cross-checks -> fact base
memo:  questions -> tested thesis -> page copy and claim audits -> IC and compliance review -> gate -> PPTX/PDF
       The optional prose path retains section reviews and hill-climbing rounds; older runs resume there.
decks: write each slide -> fact-check each -> banker critic -> compliance reviewer ->
       revise flagged slides -> hill-climbing rounds -> code compliance gate -> PPTX/PDF

Every step's output is cached under RUN/steps/<phase>/ keyed by its inputs, so a
restarted phase continues from the last completed step instead of starting over.
"""
from __future__ import annotations

import json
import os
import datetime
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from delivery.deal_documents.llm import ModelResponseError, RecordedModel
from delivery.deal_documents.runs import RunCancelled, Tracker
from delivery.deal_documents.public_sources import public_basis

PIPELINE_VERSION = 'deal-documents-v4-code-written-evidence'
# Independent steps (section drafts, fact-checks, the IC and compliance reviews, revisions) run this many at a time.
# Each in-flight model call needs its own context cache in the Ollama server (OLLAMA_NUM_PARALLEL), so raise both
# together and only where memory allows; 1 runs every step in order.
PARALLEL = max(1, int(os.environ.get('DEAL_DOCUMENTS_PARALLEL', '1')))


def parallel(jobs):
    """Run zero-argument callables, PARALLEL at a time; results in job order. The first exception is raised."""
    if PARALLEL == 1 or len(jobs) < 2:
        return [job() for job in jobs]
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        return [future.result() for future in [pool.submit(job) for job in jobs]]


def _write(path: Path, data, binary=False):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(data) if binary else temporary.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def run_phase(conn, run, phase, token, *, db_path=None):
    tracker = Tracker(conn, run, phase, token, PIPELINE_VERSION)
    model = RecordedModel(run['run_dir'], run['model'])
    call = model.json
    call_state = threading.local()

    def observed(name, profile, *args, **kwargs):
        if getattr(call_state, 'active', False):
            return call(name, profile, *args, **kwargs)
        if phase == 'memo' and run['data'].get('generation_path') == 'page_first' and profile == 'review' and not kwargs.get('settings'):
            from delivery.deal_documents.llm import PROFILES
            kwargs['settings'] = {**PROFILES[profile], 'thinking_chars': 2400,
                                  'options': {**PROFILES[profile]['options'], 'num_predict': 4000}}
        call_state.active = True
        try:
            return tracker.model_call(lambda: call(name, profile, *args, **kwargs), name, profile)
        finally:
            call_state.active = False
    model.json = observed
    try:
        {'facts': facts_phase, 'memo': memo_phase, 'decks': decks_phase}[phase](tracker, model, run, db_path)
        from delivery.deal_documents import diligence, runs
        diligence.sync_requests(conn, run['tenant_id'], run['workspace_id'],
                                runs.get(conn, run['tenant_id'], run['workspace_id']), 'document-worker')
    except RunCancelled:
        tracker.finish('cancelled')
        return 'cancelled'
    except Exception as exc:  # recorded for the UI; the step records keep the detail
        tracker.finish('failed', error=f'{type(exc).__name__}: {exc}'[:500])
        return 'failed'
    tracker.finish('needs_approval', error=None)
    return 'needs_approval'


# ------------------------------------------------------------------- facts

def facts_phase(tracker, model, run, db_path):
    from delivery.deal_documents.facts import cross_check, extract_facts, select_summary_sheets, write_fact_base
    from delivery.deal_documents.sources import load_sources, sheet_facts, sheet_text_cells
    from delivery.deal_documents.ledger import digest
    ocr_root = run['data'].get('ocr_root')
    units, sheets = load_sources(db_path, run['tenant_id'], run['deal_id'], Path(ocr_root) if ocr_root else None)
    units = units + [unit for unit in (sheet_text_cells(sheet) for sheet in sheets) if unit]
    tracker.plan([(f'extract:{unit.id}', f'Read {unit.document}, {unit.location}', 'extract') for unit in units] +
                 [('sheets', 'Choose the workbook summary sheets', 'select'), ('crosscheck', 'Reconcile figures across documents', 'crosscheck'),
                  ('write', 'Save the fact base', 'render')])
    accepted, rejected = [], []
    for unit in units:
        inputs = [unit.id, unit.text(), unit.image and Path(unit.image).stat().st_size]
        result = tracker.step(f'extract:{unit.id}', inputs, lambda unit=unit: dict(zip(('accepted', 'rejected'), extract_facts(model, [unit]))),
                              detail=lambda r: f'{len(r["accepted"])} facts, {len(r["rejected"])} rejected')
        accepted += [{**fact, 'source_sha256': digest(unit.text()), 'source_hash_scope': 'extracted_source_unit'} for fact in result['accepted']]
        rejected += result['rejected']
    summary = tracker.step('sheets', [sheet.preview() for sheet in sheets], lambda: select_summary_sheets(model, sheets),
                           detail=lambda r: ', '.join(r))
    cells = [{**fact, 'source_sha256': digest([sheet.document, sheet.name, sheet.headers, sheet.rows]), 'source_hash_scope': 'extracted_workbook_sheet'}
             for sheet in sheets if sheet.id in summary for fact in sheet_facts(sheet)]
    checked = tracker.step('crosscheck', [accepted, summary], lambda: dict(zip(('checks', 'observations'),
                                                                             cross_check(model, accepted, cells, sheets, summary))),
                           detail=lambda r: f'{len(r["checks"])} checks, {sum(c["status"] == "inconsistent" for c in r["checks"])} '
                                            f'inconsistent, {len(r["observations"])} observations')
    tracker.step('write', [accepted, checked], lambda: write_fact_base(Path(run['run_dir']), accepted, rejected, summary, cells,
                                                                       checked['checks'], checked['observations']) or True)


# ------------------------------------------------------------------- memo

def _fact_base(run):
    """The approved facts, plus the company's answers so far as citable facts."""
    from delivery.deal_documents.questions import answer_facts
    approval = run['data']['phases']['facts']['approvals']['operator']
    fact_base = json.loads((Path(run['run_dir']) / 'facts.json').read_text())
    fact_base['human_notes'] = approval.get('notes', '')
    fact_base['facts'] += answer_facts(run['data'].get('questions', []))
    review = Path(run['run_dir']) / 'baseline_review.json'
    if review.exists():
        fact_base['ledger_review'] = json.loads(review.read_text())
    if run['data'].get('baseline_choices'):
        fact_base.setdefault('ledger_review', {}).setdefault('selections', {}).update(run['data']['baseline_choices'])
    if run['data'].get('baseline_mappings'):
        fact_base.setdefault('ledger_review', {}).setdefault('mappings', {}).update(run['data']['baseline_mappings'])
    if fact_base.get('ledger_review'):
        from delivery.deal_documents.ledger import digest
        return fact_base, digest([approval['sha256'], fact_base['ledger_review']])
    return fact_base, approval['sha256']


def _ledger(run_dir, documents, fact_base, prefix='', *, exported=False):
    from delivery.deal_documents import ledger
    report = ledger.tie_out(documents, fact_base)
    if exported:
        from delivery.deal_documents import pages
        index = ledger.observations(ledger.canonical(fact_base))
        source_lines = {(name, n): pages.source_line(page, index) for name, built in documents.items() for n, page in enumerate(built, 1)}
        report = ledger.audit_exports(report, documents, run_dir, source_lines)
    _write(run_dir / f'{prefix}source_ledger.json', report)
    _write(run_dir / f'{prefix}source_ledger.md', ledger.markdown(report))
    if not prefix:
        _write(run_dir / 'financial_baseline.json', report['baseline'])
    return ledger.gate_section(report)


def run_climb(tracker, model, parts, *, document, kind, label, rewrite_part, before, index, notes=''):
    """Hill-climb `parts` ({key: part}) through tracked, cached steps. One helper for sections and slides."""
    from delivery.deal_documents.climb import PASSES, climb, evaluate

    def assess(items, number):
        tracker.add([(f'score{number}:{key}', f'{label} check, round {number}: {part["title"]}', 'score') for key, part in items], before=before)
        def one(key, part):
            return tracker.step(f'score{number}:{key}', [part, notes], lambda: evaluate(model, part, index, document, notes),
                                detail=lambda r: f'{(r["score"] or {}).get("overall", "no")} points, {r["issues"]} issues, {r["problems"]} problems')
        return parallel([lambda key=key, part=part: one(key, part) for key, part in items])

    def rewrite(items, number):
        def one(key, part, advice):
            return tracker.step(f'climb{number}:{key}', [part, advice], lambda: rewrite_part(key, part, advice),
                                detail=lambda r: r['state'].replace('_', ' '))
        return parallel([lambda key=key, part=part, advice=advice: one(key, part, advice) for key, part, advice in items])

    def on_pass(number, todo):
        titles = {key: parts[key]['title'] for key in todo}
        tracker.note(climb_rounds=PASSES - number, climb_parts=len(todo))
        tracker.add([(f'climb{number}:{key}', f'Improve, round {number}: {titles[key]}', kind) for key in todo], before=before)
    tracker.note(climb_rounds=PASSES, climb_parts=len(parts))
    result = climb(parts, assess, rewrite, on_pass, on_round=tracker.round)
    tracker.note(climb_rounds=0, climb_parts=0)
    return result


def memo_phase(tracker, model, run, db_path):
    if run['data'].get('generation_path', 'prose') == 'page_first':
        return page_first_phase(tracker, model, run, db_path)
    from delivery.deal_documents import compliance, deck_render, im, pages, readings
    from delivery.deal_documents import questions as asking
    from delivery.deal_documents.decks import tables_from_facts
    from delivery.deal_documents.memo import SECTIONS, findings_summary
    from delivery.deal_documents.review import (compliance as compliance_review, critic, fact_check, known_numbers, notes_for,
                                                proposes_unknown_number)
    run_dir = Path(run['run_dir'])
    fact_base, facts_sha = _fact_base(run)
    index = {fact['id']: fact for fact in fact_base['facts'] + fact_base['workbook_cells']}
    by_key = {section['key']: section for section in SECTIONS}
    _supersede(run_dir, MEMO_OUTPUTS)
    progress, progress_lock = {}, threading.Lock()

    def show(section):
        """Rewrite the review copy with every section drafted so far, so review can start before the run ends."""
        with progress_lock:
            progress[section['section']] = section
            done = [progress[s['key']] for s in SECTIONS if s['key'] in progress]
            _write(run_dir / 'memo.md', progress_markdown(done, len(SECTIONS), public_basis(fact_base)))
        return section
    tracker.plan([('questions', 'Work out what to ask the company', 'question'),
                  ('thesis', 'Decide the investment thesis and test it', 'write')] +
                 [(f'write:{s["key"]}', f'Write: {s["title"]}', 'write') for s in SECTIONS] +
                 [(f'check:{s["key"]}', f'Fact-check: {s["title"]}', 'check') for s in SECTIONS] +
                 [('critic', 'Investment-committee review of the whole memo', 'review'),
                  ('compliance_review', 'Compliance reviewer (questions for counsel)', 'review')] +
                 [(f'revise:{s["key"]}', f'Revise: {s["title"]}', 'revise') for s in SECTIONS] +
                 [(f'score0:{s["key"]}', f'Agent check, round 0: {s["title"]}', 'score') for s in SECTIONS] +
                 [(f'audit:{s["key"]}', f'Claim audit: {s["title"]}', 'write') for s in SECTIONS] +
                 [('final_compliance', 'Compliance reviewer on the final memo', 'review'),
                  ('gate', 'Code compliance gate', 'gate'), ('pages', 'Build the memorandum pages', 'write'), ('render', 'Render PowerPoint and PDF', 'render')])
    # Answers are part of what a draft is written from, so a changed answer cannot reuse an older draft.
    base = [facts_sha, fact_base['human_notes'], [fact for fact in fact_base['facts'] if fact.get('source') == 'company_answer']]
    # Most of what the company must answer is known from the facts alone, so it is asked before hours of writing.
    found = asking.candidates(fact_base)
    asked = tracker.step('questions', [found], lambda: asking.ask(model, fact_base, [s['key'] for s in SECTIONS], found),
                         detail=lambda r: f'{len(r)} questions, {sum(q["severity"] == "blocker" for q in r)} blocking')
    tracker.set_questions(asked)
    tables = tables_from_facts(fact_base['facts'])
    results = readings.build(tables, index)
    thesis = tracker.step('thesis', base + [im.VERSION, results], lambda: im.write_thesis(model, fact_base, results, index),
                          detail=lambda r: f'{len(r["merits"])} merits kept, {len(r["dropped"])} dropped')
    _write(run_dir / 'thesis.json', thesis)

    def write(spec, earlier='', notes='', previous=None):
        try:
            return im.write_section(model, spec, thesis, fact_base, tables, results, index, earlier, notes, previous)
        except ModelResponseError as exc:
            return {'section': spec['key'], 'title': spec['title'], 'state': 'failed', 'paragraphs': [], 'calculations': [],
                    'results': {}, 'problems': [str(exc)]}

    def described(section):
        return f'{section["state"].replace("_", " ")}, {len(section["problems"])} open problems, {len(section.get("removed_sentences", []))} sentences removed'

    def write_step(spec, earlier=''):
        return show(tracker.step(f'write:{spec["key"]}', base + [im.VERSION, thesis, spec, earlier], lambda: write(spec, earlier), detail=described))

    def body(sections):
        return '\n\n'.join(f'## {s["title"]}\n{s.get("headline", "")}\n' + '\n'.join(p['text'] for p in s['paragraphs']) for s in sections)

    # Every section but the summary drafts independently; the summary is written from the others.
    draft = parallel([lambda spec=spec: write_step(spec) for spec in SECTIONS if spec['key'] != 'summary'])
    draft += [write_step(by_key['summary'], body(draft))]
    issues, failures = [], []

    def check_step(section):
        def check():
            try:
                return {'issues': fact_check(model, section, index, fact_base['human_notes'])}
            except ModelResponseError as exc:
                return {'issues': [], 'failure': f'fact check {section["section"]}: {exc}'}
        return tracker.step(f'check:{section["section"]}', [section, fact_base['human_notes']], check,
                            detail=lambda r: r.get('failure') or f'{sum(i["quote_verified"] for i in r["issues"])} issues')
    for result in parallel([lambda section=section: check_step(section) for section in draft]):
        issues += result['issues']
        failures += [result['failure']] if result.get('failure') else []
    findings = findings_summary(fact_base)
    notices = compliance.notices(run['company'], fact_base)

    def run_critic():
        try:
            found, overall = critic(model, draft, findings)
            return {'issues': found, 'overall': overall}
        except ModelResponseError as exc:
            return {'issues': [], 'overall': '', 'failure': f'critic: {exc}'}
    def run_compliance():
        try:
            areas, found = compliance_review(model, draft, notices=notices)
            return {'areas': areas, 'issues': found}
        except ModelResponseError as exc:
            return {'areas': [], 'issues': [], 'failure': f'compliance: {exc}'}
    # The IC critic and the compliance reviewer read the same draft independently.
    reviewed, compliant = parallel([
        lambda: tracker.step('critic', [draft, findings], run_critic,
                             detail=lambda r: r.get('failure') or f'{sum(i["quote_verified"] for i in r["issues"])} issues'),
        lambda: tracker.step('compliance_review', [draft], run_compliance,
                             detail=lambda r: r.get('failure') or f'{sum(a["status"] != "adequate" for a in r["areas"])} '
                                                                  'areas need action')])
    issues += reviewed['issues'] + compliant['issues']
    failures += [r['failure'] for r in (reviewed, compliant) if r.get('failure')]
    review = {'issues': issues, 'overall': reviewed['overall'], 'compliance_areas': compliant['areas'], 'failures': failures,
              'thesis_dropped': thesis['dropped']}
    # Answers given since this phase started become citable now, without waiting for another run.
    answers = tracker.live_questions()
    fact_base['facts'] = [fact for fact in fact_base['facts'] if fact.get('source') != 'company_answer'] + asking.answer_facts(answers)
    index.update({fact['id']: fact for fact in fact_base['facts'] if fact.get('source') == 'company_answer'})

    flagged = []
    known = known_numbers(index, draft)
    for issue in review['issues']:
        issue['unverified_number'] = proposes_unknown_number(issue, known)
    _write(run_dir / 'memo_review.json', review)
    for section in draft:
        notes = notes_for(section['section'], review, known)
        if section['problems']:
            notes += ('\n' if notes else '') + '\n'.join(f'- [code validation] {problem}' for problem in section['problems'])
        for item in section.get('removed_sentences', []):
            notes += (f'\n- [code validation] this sentence was removed: "{item["sentence"]}" because '
                      f'{"; ".join(item["reasons"])}. If the point matters, state it correctly.')
        # A section is rewritten only when something is wrong with it or an answer bears on it.
        answered = asking.answer_notes(answers, section['section'])
        if section['paragraphs'] and (notes or answered):
            flagged.append((section['section'], '\n'.join(filter(None, (notes, answered)))))
    notes_by_key = dict(flagged)
    for section in draft:
        if section['section'] not in notes_by_key:
            tracker.drop(f'revise:{section["section"]}')

    def revise_step(section, earlier=''):
        key = section['section']
        if key not in notes_by_key:
            return section
        revised = tracker.step(f'revise:{key}', base + [thesis, section, notes_by_key[key], earlier],
                               lambda: write(by_key[key], earlier, notes_by_key[key], section), detail=described)
        # Keep the revision unless it failed or left more wrong than the reviewed draft.
        if revised['state'] == 'failed' or len(revised['problems']) > len(section['problems']):
            return show({**section, 'revision_rejected': revised['problems'][:5]})
        return show({**revised, 'revised_from_review': True, 'review_notes': notes_by_key[key]})
    # The summary is revised last, from the other revised sections.
    final = parallel([lambda section=section: revise_step(section) for section in draft if section['section'] != 'summary'])
    final += [revise_step(section, body(final)) for section in draft if section['section'] == 'summary']

    def improve(key, section, advice):
        earlier = body([s for s in final if s['section'] != 'summary']) if key == 'summary' else ''
        better = write(by_key[key], earlier, advice, section)
        return better if better['state'] == 'failed' else show(better)
    # The writers keep going while the agents find a better version; only what improves is kept.
    best, assessed, climbed = run_climb(tracker, model, {s['section']: s for s in final}, document='investment memorandum', kind='revise',
                                        label='Agent', rewrite_part=improve, before='final_compliance', index=index,
                                        notes=fact_base['human_notes'])
    final = [show(best[section['section']]) for section in final]
    review['climb'] = climbed

    # The last agents read each sentence against all the evidence: what does not follow goes back to the writer once, then comes out.
    narrative = [fact for fact in fact_base['facts'] if not fact.get('table')]

    def audit_step(section):
        key = section['section']

        def run():
            try:
                return im.audit_section(model, section, narrative, lambda advice: improve(key, section, advice))
            except ModelResponseError as exc:
                return {**section, 'state': 'needs_review', 'problems': [*section['problems'], f'claim audit failed: {exc}']}
        return show(tracker.step(f'audit:{key}', [im.AUDIT_VERSION, section], run,
                                 detail=lambda r: f'{len(r.get("audit", []))} sentences refused by both agents, {len(r.get("audit_noted", []))} by one'))
    final = parallel([lambda section=section: audit_step(section) for section in final])

    def with_merits(section):
        if section['section'] != 'summary':
            return section
        # A case that is short of merits is a fault in the memorandum, not a note in a log.
        problems = [*section['problems'], *(f'thesis: {problem}' for problem in thesis['problems'])]
        return {**section, 'merits': im.merit_lines(thesis, results), 'problems': problems, 'state': 'needs_review' if problems else section['state']}
    final = [with_merits(section) for section in im.drop_repeats(final)]
    questions_now = tracker.live_questions()
    tracker.set_readiness(asking.readiness(final, assessed, questions_now))
    # The compliance reviewer reads the final text too: that is what counsel signs off.
    def run_final_compliance():
        try:
            areas, found = compliance_review(model, final, name='final-compliance', notices=notices)
            return {'areas': areas, 'issues': found}
        except ModelResponseError as exc:
            return {'areas': [], 'issues': [], 'failure': f'final compliance: {exc}'}
    closing = tracker.step('final_compliance', [final], run_final_compliance,
                           detail=lambda r: r.get('failure') or f'{sum(a["status"] in ("needs_change", "missing") for a in r["areas"])} '
                                                                'areas need action')
    review['final_compliance'] = closing
    if closing['areas']:
        review['compliance_areas'] = closing['areas']
    review['failures'] += [closing['failure']] if closing.get('failure') else []
    _write(run_dir / 'memo_review.json', review)
    # The memorandum leaves questioned figures out, so the draft says so, and the gate holds release until they are settled.
    unsettled = sum(question['severity'] == 'high' and not question.get('answer') for question in questions_now)
    if unsettled:
        notices = [*notices, ('Figures under confirmation (draft only)',
                              f'{unsettled} figures or definitions are being confirmed with the company. Remove this note once they are settled; '
                              'the draft is not to be circulated before then.')]
    assessment = tracker.step('gate', [final, closing, questions_now], lambda: compliance.assess(final, fact_base, closing['areas'], closing['issues'], open_questions=questions_now),
                              detail=lambda r: f'{len(r["blockers"])} release blockers, {len(r["counsel_questions"])} counsel questions')
    _write(run_dir / 'memo.json', final)
    markdown = memo_markdown(final, review)
    if public_basis(fact_base):
        markdown = markdown.replace('\n', '\n\n' + public_basis(fact_base) + '\n', 1)
    _write(run_dir / 'memo.md', markdown)
    _write(run_dir / 'open_items.md', asking.open_items_markdown(questions_now, run['company']))
    # The memorandum investors read is pages of exhibits; the reviewed text above supplies its case. On the GPU when it is up, otherwise here.
    profile = 'write' if 'write' in getattr(model, 'routes', {}) else 'check'
    built = tracker.step('pages', [pages.VERSION, facts_sha, im.merit_lines(thesis, results)],
                         lambda: pages.write_all(model, fact_base, pages.build(fact_base, im.merit_lines(thesis, results)), pages.demonstrations(), profile),
                         detail=lambda r: f'{len(r)} pages')
    _write(run_dir / 'pages.json', built)
    _write(run_dir / 'baseline.json', pages.baseline(built))
    # Investors read the pages, so their words pass the same gate as the text behind them.
    numerical_review = _ledger(run_dir, {'investment_memorandum': built}, fact_base)
    assessment = compliance.assess([*final, *pages.as_sections(built), numerical_review], fact_base, closing['areas'], closing['issues'], open_questions=questions_now)
    _write(run_dir / 'compliance.json', assessment)
    _write(run_dir / 'compliance.md', compliance.markdown(assessment))
    # Reruns move earlier files aside, so a saved render counts only while its files exist.
    rendered = all((run_dir / f'investment_memorandum.{fmt}').exists() for fmt in ('pptx', 'pdf'))

    def render_pages():
        deck = pages.render(run['company'], notices, built, fact_base, datetime.date.today().strftime('%B %Y'))
        _write(run_dir / 'investment_memorandum.pptx', deck, binary=True)
        _write(run_dir / 'investment_memorandum.pdf', deck_render.to_pdf(deck), binary=True)
        return True
    tracker.step('render', [built, rendered, notices], render_pages)
    numerical_review = _ledger(run_dir, {'investment_memorandum': built}, fact_base, exported=True)
    assessment = compliance.assess([*final, *pages.as_sections(built), numerical_review], fact_base, closing['areas'], closing['issues'], open_questions=questions_now)
    _write(run_dir / 'compliance.json', assessment)
    _write(run_dir / 'compliance.md', compliance.markdown(assessment))


def _page_sections(built, fact_base):
    from delivery.deal_documents import pages
    sections = pages.as_sections(built)
    for section, page in zip(sections, built):
        # The gate and whole-document reviewers must see every printed claim, including the merit grid.
        if page['key'] != 'risks':
            section['paragraphs'] += [{'text': pages._exhibit_text(page)}] if page['exhibits'] else []
        cites = list(dict.fromkeys([*page['cells'], *(fact['id'] for fact in pages._context(page, fact_base['facts']))]))
        section.update(state='needs_review' if page.get('problems') else 'valid', results={}, problems=page.get('problems', []))
        section['paragraphs'] = [{'kind': 'analysis', 'cites': cites, **paragraph} for paragraph in section['paragraphs']]
    return sections


def _page_plan(fact_base, merits):
    from delivery.deal_documents import pages
    from delivery.deal_documents.memo import SECTIONS
    plan = pages.build(fact_base, merits)
    covered = {pages.SECTIONS.get(page['key'], page['key']) for page in plan}
    if any(page['key'] in ('forecast', 'forecast_table') for page in plan):
        covered.add('projections')
    for spec in SECTIONS:
        if spec['key'] in covered or not spec['topics']:
            continue
        topics = spec['topics'] if spec['key'] == 'company' else spec['topics'][:1]
        facts = [fact for fact in fact_base['facts'] if not fact.get('table') and fact['topic'] in topics]
        if not facts:
            continue
        # Narrative evidence can support a short diligence page without first writing a prose section.
        points = pages.key_points(fact_base['facts'], topics)
        page = {'key': spec['key'], 'kind': 'copy', 'brief': spec['brief'], 'topics': spec['topics'],
                'cells': [fact['id'] for fact in facts], 'exhibits': {'grid': points[0]} if points else {}, 'title': '', 'schedule': False, 'takeaways': [], 'pick': True}
        position = next((i for i, item in enumerate(plan) if item['key'] in ('financials', 'forecast_table')), len(plan))
        plan.insert(position, page)
    return plan


def page_first_phase(tracker, model, run, db_path):
    from delivery.deal_documents import compliance, deck_render, im, pages, readings
    from delivery.deal_documents import questions as asking
    from delivery.deal_documents.decks import tables_from_facts
    from delivery.deal_documents.climb import better, score_unit
    from delivery.deal_documents.memo import SECTIONS, findings_summary
    from delivery.deal_documents.review import compliance as compliance_review, critic, known_numbers, notes_for

    run_dir = Path(run['run_dir'])
    fact_base, facts_sha = _fact_base(run)
    base = [facts_sha, fact_base['human_notes'], [fact for fact in fact_base['facts'] if fact.get('source') == 'company_answer']]
    tracker.plan([('pf:archive', 'Keep the previous version available', 'render'),
                  ('pf:questions', 'Work out what to ask the company', 'question'),
                  ('pf:thesis', 'Test the investment thesis against the evidence', 'write'),
                  ('pf:critic', 'Investment-committee review of the pages', 'review'),
                  ('pf:compliance', 'Compliance review of the pages', 'review'),
                  ('pf:final_compliance', 'Compliance review of the final page copy', 'review'),
                  ('pf:gate', 'Code compliance gate on the final pages', 'gate'),
                  ('pf:render', 'Render the reviewed memorandum', 'render')])
    generation = run['data']['phases']['memo'].get('queued_at')
    previous = tracker.step('pf:archive', [generation], lambda: _supersede(run_dir, (*MEMO_OUTPUTS, 'pages.preview.json', 'investment_memorandum.preview.pdf')))
    found = asking.candidates(fact_base)
    asked = tracker.step('pf:questions', [found], lambda: asking.ask(model, fact_base, [s['key'] for s in SECTIONS], found),
                         detail=lambda r: f'{len(r)} questions')
    tracker.set_questions(asked)
    index = {fact['id']: fact for fact in fact_base['facts'] + fact_base['workbook_cells']}
    results = readings.build(tables_from_facts(fact_base['facts']), index)
    thesis = tracker.step('pf:thesis', base + [im.VERSION, results], lambda: im.write_thesis(model, fact_base, results, index),
                          detail=lambda r: f'{len(r["merits"])} merits kept, {len(r["dropped"])} dropped')
    _write(run_dir / 'thesis.json', thesis)
    plan = _page_plan(fact_base, im.merit_lines(thesis, results))
    built = [{**page, 'page_status': 'pending'} for page in plan]
    preview_path = run_dir / 'pages.preview.json'
    if preview_path.exists():
        saved = json.loads(preview_path.read_text())
        if saved.get('generation') == generation:
            by_key = {page['key']: page for page in saved['pages']}
            built = [by_key.get(page['key'], page) for page in built]
    notices = compliance.notices(run['company'], fact_base)
    if any(question['severity'] == 'high' and not question.get('answer') for question in tracker.live_questions()):
        notices = [*notices, ('Figures under confirmation (draft only)',
                             'Figures or definitions are being confirmed with the company. This draft cannot be circulated before they are settled.')]
    preview_notices = [*notices, ('In progress: not reviewed', 'Page copy and compliance checks are still being completed. Pending pages are marked. This draft cannot be circulated.')]
    when = datetime.date.today().strftime('%B %Y')
    shots = pages.demonstrations()
    assessed = {}
    steps = []
    for number, page in enumerate(plan):
        steps += [(f'pf:write:{page["key"]}', f'Write page: {page["title"] or page["brief"]}', 'page_copy'),
                  (f'pf:preview:{number}:written', f'Render preview after writing page {number + 1}', 'render'),
                  (f'pf:audit:{page["key"]}', f'Audit page with both readers: {page["title"] or page["brief"]}', 'page_audit'),
                  (f'pf:preview:{number}:audited', f'Render preview after auditing page {number + 1}', 'render'),
                  (f'pf:score:{page["key"]}', f'Score page copy: {page["title"] or page["brief"]}', 'score')]
    tracker.add(steps, before='pf:critic')

    def save_progress():
        statuses = [{'key': page['key'], 'title': page['title'] or page['brief'], 'state': page['page_status'],
                     'problems': page.get('problems', [])} for page in built]
        _write(run_dir / 'pages.preview.json', {'generation': generation, 'pages': built})
        tracker.note(pages=statuses)

    def publish():
        preview = []
        for page in built:
            if page['page_status'] == 'pending':
                preview.append({**page, 'title': 'Pending page: ' + page['key'].replace('_', ' '), 'exhibits': {},
                                'takeaways': ['PENDING: page copy has not been written.']})
            else:
                preview.append({**page, 'title': page['title'] or page['brief']})
        try:
            deck = pages.render(run['company'], preview_notices, preview, fact_base, when, 'Investment memorandum - IN PROGRESS')
        except ValueError as exc:  # a preview that cannot be drawn must not stop the pages behind it; the final render stays strict
            return f'Preview not updated: {exc}'
        _write(run_dir / 'investment_memorandum.preview.pdf', deck_render.to_pdf(deck), binary=True)

    def write(page, notes=''):
        try:
            if page['schedule']:
                return page
            candidate = pages.write_copy(model, page, fact_base['facts'], shots, 'write', notes, fast=True)
            checked = validate_copy(candidate)
            if checked.get('copy_validation'):
                advice = '\n'.join([notes, *checked['copy_validation']])
                candidate = pages.write_copy(model, page, fact_base['facts'], shots, 'write', advice, fast=True)
                checked = validate_copy(candidate)
            return checked
        except ModelResponseError as exc:
            return {**page, 'failure': str(exc), 'problems': [f'page writing failed: {exc}']}

    def validate_copy(page):
        from delivery.deal_documents.facts import numbers_in
        cited = [fact for fact in fact_base['facts'] if fact['id'] in page['cells']]
        cited += pages._context(page, fact_base['facts'])
        allowed = [number for fact in cited for number in numbers_in(fact['statement'])]
        if page['key'] != 'risks':
            allowed += numbers_in(pages._exhibit_text(page))
        own_results = {key: value for key, value in results.items() if set(value['facts']) & set(page['cells'])}
        found = []

        def keep(text):
            problems = im.text_problems(text, pages.SECTIONS.get(page['key'], page['key']), cited, own_results, index, allowed)
            found.extend(problems)
            return not problems
        title = page['title'] if keep(page['title']) else ''
        takeaways = [text for text in page['takeaways'] if keep(text)]
        exhibits = dict(page['exhibits'])
        if page['key'] == 'risks' and 'grid' in exhibits:
            exhibits['grid'] = {**exhibits['grid'], 'rows': [row for row in exhibits['grid']['rows'] if keep(' '.join(row))]}
        return {**page, 'title': title, 'takeaways': takeaways, 'exhibits': exhibits, 'copy_validation': found,
                'problems': [*page.get('problems', []), *found]}

    def audit(page, spec):
        try:
            evidence = [fact for fact in fact_base['facts'] if not fact.get('table') or fact['id'] in page['cells']]
            if page['key'] == 'highlights':
                evidence += [{'statement': line} for line in readings.lines(results)]
            return pages.audit_copy(model, page, evidence, lambda notes: write(spec, notes), full=True, human_notes=fact_base['human_notes'])
        except ModelResponseError as exc:
            return {**page, 'failure': str(exc), 'problems': [*page.get('problems', []), f'page audit failed: {exc}']}

    def show(position, page, state):
        built[position] = {**page, 'page_status': 'needs_review' if page.get('problems') or page.get('failure') else state}
        save_progress()
        key = f'pf:preview:{position}:{state}'
        tracker.add([(key, f'Render preview after page {position + 1}: {state}', 'render')], before='pf:critic')
        tracker.step(key, [built, (run_dir / 'investment_memorandum.preview.pdf').exists()], lambda: publish() or True,
                    detail=lambda r: r if isinstance(r, str) else '')

    def score(page, key):
        section = _page_sections([page], fact_base)[0]
        result = tracker.step(key, [section], lambda: score_unit(model, section, 'investment memorandum page'),
                              detail=lambda r: f'{r["overall"]}/100')
        assessed[page['key']] = {'score': result, 'issues': len(page.get('audit', [])), 'problems': len(page.get('problems', [])),
                                 'failures': [page['failure']] if page.get('failure') else []}
        return result

    for position, spec in enumerate(plan):
        answers = tracker.live_questions()
        fact_base['facts'] = [fact for fact in fact_base['facts'] if fact.get('source') != 'company_answer'] + asking.answer_facts(answers)
        base[2] = [fact for fact in fact_base['facts'] if fact.get('source') == 'company_answer']
        index = {fact['id']: fact for fact in fact_base['facts'] + fact_base['workbook_cells']}
        page = tracker.step(f'pf:write:{spec["key"]}', base + [pages.VERSION, spec], lambda spec=spec: write(spec),
                            detail=lambda r: r.get('failure') or 'Page copy saved; claim audit follows')
        show(position, page, 'written')
        checked = tracker.step(f'pf:audit:{spec["key"]}', [im.AUDIT_VERSION, page, base], lambda page=page, spec=spec: audit(page, spec),
                               detail=lambda r: r.get('failure') or f'{len(r.get("audit", []))} refused lines, {len(r.get("audit_noted", []))} audit notes')
        show(position, checked, 'audited')
        score(checked, f'pf:score:{spec["key"]}')
        tracker.round({'round': 0, 'kept': sorted(assessed), 'dropped': [],
                       'scores': {key: value['score']['overall'] for key, value in assessed.items()}})

    sections = _page_sections(built, fact_base)
    index.update({fact['id']: fact for fact in fact_base['facts'] if fact.get('source') == 'company_answer'})
    findings = findings_summary(fact_base)

    def review_pages():
        issues, overall = critic(model, sections, findings)
        return {'issues': issues, 'overall': overall}

    reviewed = tracker.step('pf:critic', [sections, findings], review_pages)

    def review_compliance(name, current):
        areas, issues = compliance_review(model, current, name=name, notices=notices)
        return {'areas': areas, 'issues': issues}

    compliant = tracker.step('pf:compliance', [sections, notices], lambda: review_compliance('page-compliance', sections))
    review = {'issues': reviewed['issues'] + compliant['issues'], 'overall': reviewed['overall'],
              'compliance_areas': compliant['areas'], 'failures': [], 'thesis_dropped': thesis['dropped']}
    known = known_numbers(index, sections)
    from delivery.deal_documents.facts import numbers_in
    known += numbers_in('\n'.join(pages._exhibit_text(page) for page in built))
    initial_round = {'round': 0, 'kept': sorted(assessed), 'dropped': [],
                     'scores': {key: value['score']['overall'] for key, value in assessed.items()}}
    changes = {}
    for position, (spec, section) in enumerate(zip(plan, sections)):
        notes = notes_for(section['section'], review, known)
        if not notes or spec['schedule']:
            continue
        key = spec['key']
        tracker.add([(f'pf:revise:{key}', f'Revise page from reviewer findings: {section["title"]}', 'page_copy'),
                     (f'pf:reaudit:{key}', f'Audit revised page: {section["title"]}', 'page_audit')], before='pf:final_compliance')
        previous_page, previous_assessment = built[position], assessed[key]
        previous_score = previous_assessment['score']['overall']
        revised = tracker.step(f'pf:revise:{key}', [base, spec, notes], lambda spec=spec, notes=notes: write(spec, notes))
        show(position, revised, 'written')
        checked = tracker.step(f'pf:reaudit:{key}', [base, revised], lambda revised=revised, spec=spec: audit(revised, spec))
        tracker.add([(f'pf:rescore:{key}', f'Score revised page: {section["title"]}', 'score')], before='pf:final_compliance')
        candidate_score = score(checked, f'pf:rescore:{key}')
        keep = better(assessed[key], previous_assessment)
        if not keep:
            assessed[key] = previous_assessment
        import difflib
        copy_text = lambda page: '\n'.join([page['title'], *page['takeaways'], pages._exhibit_text(page)])
        changes[key] = {'before_score': previous_score, 'candidate_score': candidate_score['overall'], 'kept': keep,
                        'reason': 'Accuracy first, then the existing minimum score gain' if keep else 'Candidate did not improve accuracy or meet the minimum score gain',
                        'diff': '\n'.join(difflib.unified_diff(copy_text(previous_page).splitlines(), copy_text(checked).splitlines(),
                                                              fromfile='previous', tofile='candidate', lineterm=''))}
        show(position, checked if keep else previous_page, 'audited')
        tracker.round({'round': 1, 'kept': sorted(key for key, change in changes.items() if change['kept']),
                       'dropped': sorted(key for key, change in changes.items() if not change['kept']),
                       'scores': {key: value['score']['overall'] for key, value in assessed.items()}, 'changes': changes})
    # Thesis faults remain release blockers even if no merit was safe enough to print.
    built[0]['problems'] = [*built[0].get('problems', []), *(f'thesis: {problem}' for problem in thesis['problems'])]
    sections = _page_sections(built, fact_base)
    closing = tracker.step('pf:final_compliance', [sections, notices], lambda: review_compliance('page-final-compliance', sections))
    review['final_compliance'] = closing
    review['climb'] = [initial_round]
    if changes:
        review['climb'].append({'round': 1, 'kept': sorted(key for key, change in changes.items() if change['kept']),
                                'dropped': sorted(key for key, change in changes.items() if not change['kept']),
                                'scores': {key: value['score']['overall'] for key, value in assessed.items()}, 'changes': changes})
    questions_now = tracker.live_questions()
    numerical_review = _ledger(run_dir, {'investment_memorandum': built}, fact_base)
    assessment = tracker.step('pf:gate', [sections, closing, questions_now, numerical_review],
                              lambda: compliance.assess([*sections, numerical_review], fact_base, closing['areas'], closing['issues'], open_questions=questions_now),
                              detail=lambda r: f'{len(r["blockers"])} release blockers')
    tracker.set_readiness(asking.readiness(sections, assessed, questions_now))
    _write(run_dir / 'memo.json', sections)
    _write(run_dir / 'memo.md', memo_markdown(sections, review))
    _write(run_dir / 'memo_review.json', review)
    _write(run_dir / 'open_items.md', asking.open_items_markdown(questions_now, run['company']))
    for page in built:
        if page.get('problems'):
            page['page_status'] = 'needs_review'
    _write(run_dir / 'pages.json', built)
    _write(run_dir / 'baseline.json', pages.baseline(built))
    _write(run_dir / 'compliance.json', assessment)
    _write(run_dir / 'compliance.md', compliance.markdown(assessment))
    if previous and (run_dir / 'superseded' / previous / 'pages.json').exists():
        import difflib
        old = {page['key']: page for page in json.loads((run_dir / 'superseded' / previous / 'pages.json').read_text())}
        current = {page['key']: page for page in built}
        changes = []
        for key in sorted(old.keys() | current.keys()):
            before, after = old.get(key), current.get(key)
            text = lambda page: '\n'.join([page['title'], *page['takeaways'], pages._exhibit_text(page)]) if page else ''
            if text(before) != text(after):
                changes.append({'key': key, 'change': 'added' if before is None else 'removed' if after is None else 'updated',
                                'diff': '\n'.join(difflib.unified_diff(text(before).splitlines(), text(after).splitlines(),
                                                                      fromfile='previous', tofile='current', lineterm=''))})
        tracker.note(page_changes={'previous': previous, 'changes': changes})
    save_progress()

    def render():
        deck = pages.render(run['company'], notices, built, fact_base, when)
        _write(run_dir / 'investment_memorandum.pptx', deck, binary=True)
        _write(run_dir / 'investment_memorandum.pdf', deck_render.to_pdf(deck), binary=True)
        return True
    rendered = all((run_dir / f'investment_memorandum.{fmt}').exists() for fmt in ('pptx', 'pdf'))
    tracker.step('pf:render', [built, notices, rendered], render)
    numerical_review = _ledger(run_dir, {'investment_memorandum': built}, fact_base, exported=True)
    tracker.add([('pf:export_gate', 'Code compliance gate on the exported files', 'gate')])
    assessment = tracker.step('pf:export_gate', [sections, closing, questions_now, numerical_review],
                              lambda: compliance.assess([*sections, numerical_review], fact_base, closing['areas'], closing['issues'], open_questions=questions_now))
    _write(run_dir / 'compliance.json', assessment)
    _write(run_dir / 'compliance.md', compliance.markdown(assessment))


MEMO_OUTPUTS = ('thesis.json', 'memo.json', 'memo.md', 'memo_review.json', 'compliance.json', 'compliance.md', 'open_items.md',
                'pages.json', 'investment_memorandum.pptx', 'investment_memorandum.pdf',
                'financial_baseline.json', 'source_ledger.json', 'source_ledger.md')


def _supersede(run_dir, names):
    """Move a previous run's outputs aside (never delete) so the room shows nothing stale while a phase reruns."""
    present = [name for name in names if (run_dir / name).exists()]
    if not present:
        return
    target = run_dir / 'superseded' / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    while target.exists():
        following = datetime.datetime.strptime(target.name, '%Y%m%dT%H%M%SZ') + datetime.timedelta(seconds=1)
        target = target.with_name(following.strftime('%Y%m%dT%H%M%SZ'))
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in present:
        (run_dir / name).replace(target / name)
    return target.name


def progress_markdown(sections, total, basis=None):
    lines = ['# Investment memorandum — IN PROGRESS', '',
             f'**Not reviewed. {len(sections)} of {total} sections drafted so far; fact-checks, investment-committee and '
             'compliance reviews and revisions follow. This file is replaced by the review copy when the phase finishes.**', '']
    if basis:
        lines += [basis, '']
    for section in sections:
        stage = 'revised after review' if section.get('revised_from_review') else 'first draft'
        lines += [f'## {section["title"]} ({stage}; {section["state"].replace("_", " ")})', '']
        lines += [section['headline'] + '\n'] if section.get('headline') else []
        lines += [paragraph['text'] + '\n' for paragraph in section['paragraphs']]
        lines += [f'- open problem: {problem}' for problem in section['problems']] + ['']
    return '\n'.join(lines)


def memo_markdown(sections, review):
    lines = ['# Investment memorandum — draft for review', '']
    for section in sections:
        lines += [f'## {section["title"]} ({section["state"]})', '']
        lines += [f'**{section["headline"]}**', ''] if section.get('headline') else []
        for paragraph in section['paragraphs']:
            lines += [paragraph['text'], f'<sub>{paragraph["kind"]} · cites {", ".join(paragraph["cites"])}'
                      + (f' · calcs {", ".join(paragraph.get("calculations_used", []))}' if paragraph.get('calculations_used') else '')
                      + '</sub>', '']
        used = {calc_id for paragraph in section['paragraphs'] for calc_id in paragraph.get('calculations_used', [])}
        for calc_id, result in section.get('results', {}).items():
            if calc_id not in used:
                continue
            if isinstance(result, dict):
                lines.append(f'- {calc_id}: {result["label"]} = {result["text"]} (code-computed {result["kind"]})')
            else:
                lines.append(f'- {calc_id}: {result}')
        lines += [f'- PROBLEM: {problem}' for problem in section['problems']] + ['']
    lines += ['## Reviewer output', '', f'IC critic overall: {review["overall"]}', '', '### Compliance areas', '']
    lines += [f'- {a["area"]}: {a["status"]} — {a["reason"]}' for a in review['compliance_areas']]
    lines += ['', '### Issues', '']
    lines += [f'- [{i["reviewer"]}] {i.get("section")}: "{i.get("quote", "")}" — '
              f'{i.get("problem") or i.get("type") or i.get("area")}: {i.get("fix") or i.get("change") or i.get("action")}'
              + ('' if i.get('quote_verified') else ' (quote not found in draft; not applied)')
              + (' (proposes a figure found in no fact or calculation; not applied)' if i.get('unverified_number') else '')
              for i in review['issues']]
    if review['failures']:
        lines += ['', '### Reviewer failures', ''] + [f'- {f}' for f in review['failures']]
    return '\n'.join(lines)


# ------------------------------------------------------------------- decks

DECK_OUTPUTS = ('decks.json', 'decks.md', 'deck_review.json', 'deck_compliance.json', 'deck_compliance.md',
                'pitch_deck.pptx', 'pitch_deck.pdf', 'intro_deck.pptx', 'intro_deck.pdf', 'deck_source_ledger.json', 'deck_source_ledger.md')


def decks_phase(tracker, model, run, db_path):
    from delivery.deal_documents import compliance, deck_render, pages
    from delivery.deal_documents.review import compliance as compliance_review
    run_dir = Path(run['run_dir'])
    fact_base, _ = _fact_base(run)
    memo_sha = run['data']['phases']['memo']['approvals']['operator']['sha256']
    built = json.loads((run_dir / 'pages.json').read_text())
    company = run['company']
    _supersede(run_dir, DECK_OUTPUTS)
    tracker.plan([('compliance_review', 'Compliance reviewer (questions for counsel)', 'review'),
                  ('gate', 'Code compliance gate', 'gate'), ('render', 'Render PPTX and PDF', 'render')])
    decks = pages.decks(built)
    sections = pages.as_sections(decks['pitch_deck'])
    notices = [(title, text.replace('This memorandum', 'This presentation').replace('this memorandum', 'this presentation'))
               for title, text in compliance.notices(company, fact_base)]

    def review_compliance():
        try:
            areas, found = compliance_review(model, sections, name='deck-compliance', notices=notices, document='PITCH DECK')
            return {'areas': areas, 'issues': found}
        except ModelResponseError as exc:
            return {'areas': [], 'issues': [], 'failure': f'deck-compliance: {exc}'}
    closing = tracker.step('compliance_review', [memo_sha, sections, notices], review_compliance,
                           detail=lambda r: r.get('failure') or f'{sum(a["status"] in ("needs_change", "missing") for a in r["areas"])} areas need action')
    questions_now = tracker.live_questions()
    numerical_review = _ledger(run_dir, {'investment_memorandum': built, **decks}, fact_base, 'deck_')
    assessment = tracker.step('gate', [sections, closing, questions_now, numerical_review], lambda: compliance.assess([*sections, numerical_review], fact_base, closing['areas'], closing['issues'], open_questions=questions_now),
                              detail=lambda r: f'{len(r["blockers"])} release blockers, {len(r["counsel_questions"])} counsel questions')
    _write(run_dir / 'decks.json', decks)
    _write(run_dir / 'decks.md', decks_markdown(decks, closing))
    _write(run_dir / 'deck_review.json', closing)
    _write(run_dir / 'deck_compliance.json', assessment)
    _write(run_dir / 'deck_compliance.md', compliance.markdown(assessment, 'draft pitch and introductory decks'))
    rendered = all((run_dir / f'{name}.{fmt}').exists() for name in decks for fmt in ('pptx', 'pdf'))

    def render():
        when = datetime.date.today().strftime('%B %Y')
        for name, heading in (('pitch_deck', 'Pitch deck'), ('intro_deck', 'Introduction')):
            deck = pages.render(company, notices, decks[name], fact_base, when, heading)
            _write(run_dir / f'{name}.pptx', deck, binary=True)
            _write(run_dir / f'{name}.pdf', deck_render.to_pdf(deck), binary=True)
        return True
    tracker.step('render', [decks, rendered, notices], render)
    numerical_review = _ledger(run_dir, {'investment_memorandum': built, **decks}, fact_base, 'deck_', exported=True)
    assessment = compliance.assess([*sections, numerical_review], fact_base, closing['areas'], closing['issues'], open_questions=questions_now)
    _write(run_dir / 'deck_compliance.json', assessment)
    _write(run_dir / 'deck_compliance.md', compliance.markdown(assessment, 'draft pitch and introductory decks'))


def decks_markdown(decks, closing):
    """The review copy: each deck's storyline, then what the compliance reviewer said."""
    lines = ['# Decks — draft for review', '']
    for name, chosen in decks.items():
        lines += [f'## {name.replace("_", " ").capitalize()}', '']
        for number, page in enumerate(chosen, 1):
            lines.append(f'{number}. {page["title"] or page["brief"]}')
            lines += [f'   - {text}' for text in page['takeaways']]
        lines.append('')
    lines += ['## Compliance reviewer', '']
    lines += [f'- {area["area"]}: {area["status"]} — {area["reason"]}' for area in closing['areas']]
    lines += [f'- FAILED: {closing["failure"]}'] if closing.get('failure') else []
    return '\n'.join(lines) + '\n'
