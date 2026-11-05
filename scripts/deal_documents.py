"""Phased investor-document workflow for a company data room (operator CLI).

  facts    --tenant T --deal D --out RUN [--ocr-root DIR]   phase 1: verified fact base -> RUN/facts.md
  approve  --out RUN --phase facts|memo --by NAME [--notes TEXT]
  memo     --out RUN --company NAME                          phase 2: IM draft, reviews, revision, DOCX/PDF
  decks    --out RUN --company NAME                          phase 3: pitch and intro decks, PPTX/PDF

Runs locally against loopback Ollama. RUN must be private storage. Each phase
refuses to start until the previous phase's exact output has been approved.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery.deal_documents.llm import DEFAULT_MODEL, RecordedModel  # noqa: E402

PHASE_FILES = {'facts': 'facts.json', 'memo': 'memo.json'}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data, binary=False):
    path.write_bytes(data) if binary else path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1))
    os.chmod(path, 0o600)


def _approvals(run: Path) -> dict:
    path = run / 'approvals.json'
    return json.loads(path.read_text()) if path.exists() else {}


def require_approval(run: Path, phase: str) -> dict:
    record = _approvals(run).get(phase)
    if not record:
        sys.exit(f'{phase} output has not been approved; review {run / PHASE_FILES[phase]} and run approve --phase {phase}')
    if record['sha256'] != _sha(run / PHASE_FILES[phase]):
        sys.exit(f'{phase} output changed after approval; review and approve again')
    return record


def cmd_facts(args):
    from delivery.deal_documents.facts import build_fact_base, cross_check, write_fact_base
    from delivery.deal_documents.sources import load_sources
    units, sheets = load_sources(args.db, args.tenant, args.deal, args.ocr_root)
    if args.units:
        units = [unit for unit in units if unit.id in set(args.units)]
        sheets = [sheet for sheet in sheets if sheet.id in set(args.units)]
    print('units:', ', '.join(unit.id for unit in units), '| sheets:', ', '.join(f'{s.id}={s.name}' for s in sheets), flush=True)
    model = RecordedModel(args.out, args.model)
    accepted, rejected, summary, cells = build_fact_base(model, units, sheets)
    print(f'facts: {len(accepted)} accepted, {len(rejected)} rejected; summary sheets {summary}, {len(cells)} cells', flush=True)
    checks, observations = cross_check(model, accepted, cells, sheets, summary)
    write_fact_base(args.out, accepted, rejected, summary, cells, checks, observations)
    print(f'checks: {len(checks)}, inconsistent {sum(c["status"] == "inconsistent" for c in checks)}; '
          f'observations: {len(observations)}; review {args.out / "facts.md"}', flush=True)


def source_of(item):
    """Source page/sheet id of a fact; older runs stored it only in the fact id prefix."""
    return item.get('source') or item.get('id', '').split('.')[0]


def cmd_recheck(args):
    """Re-run only the cross-checks against a saved fact base (extraction is not repeated)."""
    from delivery.deal_documents.facts import cross_check, write_fact_base
    from delivery.deal_documents.sources import load_sources
    from delivery.deal_documents.facts import _check_fact
    saved = json.loads((args.out / 'facts.json').read_text())
    units, sheets = load_sources(args.db, args.tenant, args.deal, args.ocr_root)
    units = {unit.id: unit for unit in units}
    # Re-validate earlier rejections under the current rules (no new model call).
    still_rejected, recovered = [], []
    for item in saved['rejected']:
        unit = units.get(source_of(item))
        line = item.get('line')
        if unit is None or not isinstance(line, dict) or 'statement' not in item:
            still_rejected.append(item)
            continue
        fact = {key: value for key, value in item.items() if key not in ('line', 'reason')}
        problem = _check_fact(fact, unit, line.get('d', ''))
        (still_rejected.append({**item, 'reason': problem}) if problem else recovered.append(fact))
    saved['facts'] += recovered
    saved['rejected'] = still_rejected
    print(f'recovered {len(recovered)} previously rejected facts under current validation', flush=True)
    model = RecordedModel(args.out, args.model)
    if args.reextract:
        from delivery.deal_documents.facts import extract_facts
        targets = [units[unit_id] for unit_id in args.reextract]
        accepted, rejected = extract_facts(model, targets)
        replaced = set(args.reextract)
        saved['facts'] = [f for f in saved['facts'] if source_of(f) not in replaced] + accepted
        saved['rejected'] = [r for r in saved['rejected'] if source_of(r) not in replaced] + rejected
        print(f're-extracted {sorted(replaced)}: {len(accepted)} facts, {len(rejected)} rejected', flush=True)
    checks, observations = cross_check(model, saved['facts'], saved['workbook_cells'], sheets, saved['workbook_summary_sheets'])
    write_fact_base(args.out, saved['facts'], saved['rejected'], saved['workbook_summary_sheets'], saved['workbook_cells'],
                    checks, observations, saved.get('corrections', []))
    print(f'checks: {len(checks)}, inconsistent {sum(c["status"] == "inconsistent" for c in checks)}; observations {len(observations)}')


def cmd_reevaluate(args):
    """Recompute saved checks with current code (no model call) and rewrite the fact base report."""
    from delivery.deal_documents.facts import reevaluate, write_fact_base
    saved = json.loads((args.out / 'facts.json').read_text())
    checks = reevaluate(saved['checks'], saved['facts'], saved['workbook_cells'])
    write_fact_base(args.out, saved['facts'], saved['rejected'], saved['workbook_summary_sheets'], saved['workbook_cells'],
                    checks, saved['observations'], saved.get('corrections', []))
    print(f'checks: {len(checks)}, inconsistent {sum(c["status"] == "inconsistent" for c in checks)}, '
          f'not computable {sum(c["status"] == "not_computable" for c in checks)}')


CORRECTABLE = ('basis', 'ambiguity')  # the statement text embeds metric, period and value, so those stay as extracted


def cmd_correct(args):
    """Apply reviewer corrections to fact labels from a JSON list [{id, basis|ambiguity, reason}].

    Values are never changed here (they are transcribed and checked against the source); only how a fact
    is labelled. Each change is recorded with its reviewer and reason, and the fact base must be approved again.
    """
    from delivery.deal_documents.facts import write_fact_base
    saved = json.loads((args.out / 'facts.json').read_text())
    index = {fact['id']: fact for fact in saved['facts']}
    corrections = saved.get('corrections', [])
    at = datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
    for item in json.loads(args.file.read_text()):
        fact = index[item['id']]
        for field in CORRECTABLE:
            if field in item and fact.get(field) != item[field]:
                corrections.append({'id': item['id'], 'field': field, 'before': fact.get(field), 'after': item[field],
                                    'reason': item['reason'], 'by': args.by, 'at': at})
                fact[field] = item[field]
    write_fact_base(args.out, saved['facts'], saved['rejected'], saved['workbook_summary_sheets'], saved['workbook_cells'],
                    saved['checks'], saved['observations'], corrections)
    print(f'{len(corrections)} corrections recorded; facts.json changed, so the fact base needs approval again')


def cmd_approve(args):
    target = args.out / PHASE_FILES[args.phase]
    approvals = _approvals(args.out)
    notes = args.notes or ''
    if args.notes_file:
        notes = (notes + '\n' + args.notes_file.read_text()).strip()
    approvals[args.phase] = {'sha256': _sha(target), 'approved_by': args.by, 'notes': notes,
                             'at': datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')}
    _write(args.out / 'approvals.json', approvals)
    print(f'approved {args.phase} ({approvals[args.phase]["sha256"][:12]}) by {args.by}')


def cmd_memo(args):
    from delivery.deal_documents.memo import SECTIONS, findings_summary, render_memo_file, write_memo, write_section
    from delivery.deal_documents.review import notes_for, review_memo
    approval = require_approval(args.out, 'facts')
    fact_base = json.loads((args.out / 'facts.json').read_text())
    fact_base['human_notes'] = approval['notes']
    model = RecordedModel(args.out, args.model)
    findings = findings_summary(fact_base)
    draft = write_memo(model, fact_base, args.only)
    _write(args.out / 'memo_draft.json', draft)
    print('draft:', {s['section']: s['state'] for s in draft}, flush=True)
    review = review_memo(model, draft, fact_base, findings)
    _write(args.out / 'memo_review.json', review)
    print(f'review: {len(review["issues"])} issues, failures {review["failures"]}', flush=True)
    by_key = {section['key']: section for section in SECTIONS}
    final = []
    for section in draft:
        notes = notes_for(section['section'], review)
        if notes and section['paragraphs']:
            earlier = '\n\n'.join(f'## {s["title"]}\n' + '\n'.join(p['text'] for p in s['paragraphs']) for s in final)
            try:
                revised = write_section(model, by_key[section['section']], fact_base, earlier, notes)
                revised['revised_from_review'] = True
                final.append(revised)
                continue
            except Exception as exc:  # keep the reviewed draft visible rather than dropping it
                section = {**section, 'problems': section['problems'] + [f'revision failed: {exc}']}
        final.append(section)
    _write(args.out / 'memo.json', final)
    _write(args.out / 'memo.md', memo_markdown(final, review))
    for fmt in ('docx', 'pdf'):
        _write(args.out / f'investment_memorandum.{fmt}', render_memo_file(final, fact_base, args.company, fmt), binary=True)
    print('memo:', {s['section']: s['state'] for s in final}, f'— review {args.out / "memo.md"}', flush=True)


def memo_markdown(sections, review):
    from delivery.deal_documents.pipeline import memo_markdown as render
    return render(sections, review)


def cmd_decks(args):
    from delivery.deal_documents.decks import render_deck, write_deck
    require_approval(args.out, 'memo')
    fact_base = json.loads((args.out / 'facts.json').read_text())
    memo = json.loads((args.out / 'memo.json').read_text())
    model = RecordedModel(args.out, args.model)
    for kind in ('pitch_deck', 'intro_deck'):
        deck = write_deck(model, kind, memo, fact_base, args.company)
        _write(args.out / f'{kind}.json', deck)
        for fmt in ('pptx', 'pdf'):
            _write(args.out / f'{kind}.{fmt}', render_deck(deck, fact_base, args.company, fmt), binary=True)
        print(kind, 'problems:', [problem for slide in deck['slides'] for problem in slide['problems']], flush=True)


def cmd_register(args):
    """Attach an existing run directory to a room so the UI tracks it; phase 1 history comes from its recorded calls."""
    import sqlite3
    from delivery.deal_documents import runs
    conn = sqlite3.connect(args.db, timeout=30, isolation_level=None)
    run = runs.create(conn, args.tenant, args.workspace, args.deal, args.company, args.out, args.model)
    if run['run_dir'] != str(args.out):
        sys.exit(f'room already has a run at {run["run_dir"]}')
    steps = []
    for path in sorted((args.out / 'calls').glob('*.json')):
        name = path.stem.split('-', 1)[1]
        kind = next((k for prefix, k in (('tables-', 'extract'), ('facts-', 'extract'), ('sheets', 'select'), ('checks-', 'crosscheck'))
                     if name.startswith(prefix)), None)
        if kind is None or name.endswith('-finish'):
            continue
        record = json.loads(path.read_text())
        finished = path.stat().st_mtime
        steps.append({'key': name, 'label': f'{name} (recorded call)', 'kind': kind, 'state': 'done', 'cached': False,
                      'seconds': record.get('seconds'), 'started': finished - (record.get('seconds') or 0), 'finished': finished})
    approval = _approvals(args.out).get('facts')
    sha = _sha(args.out / 'facts.json')

    def change(data):
        phase = data['phases']['facts']
        phase.update(state='needs_approval', steps=steps, started_at=min(s['started'] for s in steps) if steps else None,
                     finished_at=max(s['finished'] for s in steps) if steps else None, imported_from=str(args.out))
        if approval and approval['sha256'] == sha:
            phase['approvals']['operator'] = {'by': approval['approved_by'], 'notes': approval['notes'], 'sha256': sha,
                                              'decision': 'approved', 'at': datetime.datetime.fromisoformat(approval['at']).timestamp()}
            phase['state'] = 'approved'
    runs.update(conn, run['id'], change)
    print('registered', run['id'], 'facts phase', 'approved' if approval else 'awaiting approval')


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    facts = sub.add_parser('facts')
    facts.add_argument('--db', default='/home/investify/private/app.db')
    facts.add_argument('--tenant', required=True)
    facts.add_argument('--deal', required=True)
    facts.add_argument('--ocr-root', type=Path)
    facts.add_argument('--units', nargs='*')
    recheck = sub.add_parser('recheck')
    recheck.add_argument('--db', default='/home/investify/private/app.db')
    recheck.add_argument('--tenant', required=True)
    recheck.add_argument('--deal', required=True)
    recheck.add_argument('--ocr-root', type=Path)
    recheck.add_argument('--reextract', nargs='*', default=[], help='page/sheet unit ids to extract again and replace')
    reevaluate = sub.add_parser('reevaluate')
    approve = sub.add_parser('approve')
    approve.add_argument('--phase', required=True, choices=list(PHASE_FILES))
    approve.add_argument('--by', required=True)
    approve.add_argument('--notes')
    approve.add_argument('--notes-file', type=Path)
    memo = sub.add_parser('memo')
    memo.add_argument('--company', required=True)
    memo.add_argument('--only', nargs='*')
    decks = sub.add_parser('decks')
    decks.add_argument('--company', required=True)
    correct = sub.add_parser('correct')
    correct.add_argument('--file', required=True, type=Path)
    correct.add_argument('--by', required=True)
    register = sub.add_parser('register')
    register.add_argument('--db', default='/home/investify/private/app.db')
    register.add_argument('--tenant', required=True)
    register.add_argument('--workspace', required=True)
    register.add_argument('--deal', required=True)
    register.add_argument('--company', required=True)
    for command in (facts, recheck, reevaluate, approve, memo, decks, register, correct):
        command.add_argument('--out', required=True, type=Path)
        command.add_argument('--model', default=DEFAULT_MODEL)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.out, 0o700)
    {'facts': cmd_facts, 'recheck': cmd_recheck, 'reevaluate': cmd_reevaluate, 'approve': cmd_approve,
     'memo': cmd_memo, 'decks': cmd_decks, 'register': cmd_register, 'correct': cmd_correct}[args.command](args)


if __name__ == '__main__':
    main()
