"""Canonical observations and occurrence-level numerical review. No model calls.

Unknown meanings and unsupported workings remain exceptions. A structured-page
tie-out is not evidence that the exported PDF has been independently checked.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree

VERSION = 'ledger-v1'
NUMBER = re.compile(r'\([+-]?\d[\d,]*(?:\.\d+)?\)|[+-]?\d[\d,]*(?:\.\d+)?')
DIMENSIONS = ('entity', 'metric', 'definition', 'segment', 'unit', 'currency', 'scale',
              'basis', 'case', 'version', 'perimeter')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def label(value):
    return ' '.join(re.sub(r'[^\w%]+', ' ', str(value or '').casefold()).split())


def numeric(value):
    text = str(value).strip().replace(',', '')
    try:
        number = -float(text[1:-1]) if text.startswith('(') and text.endswith(')') else float(text)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def observations(fact_base):
    return {fact['id']: fact for fact in [*fact_base.get('facts', []), *fact_base.get('workbook_cells', [])]}


def mapped_observations(fact_base):
    mappings = fact_base.get('ledger_review', {}).get('mappings', {})
    return {key: {**fact, **mappings.get(key, {})} for key, fact in observations(fact_base).items()}


def identity(fact, fiscal_month=3):
    from delivery.deal_documents.semantics import period_of
    period = period_of(fact.get('period'), fiscal_month)
    return tuple(label(fact.get(key)) for key in DIMENSIONS) + (str(period or label(fact.get('period'))),)


def reconciliations(facts, fiscal_month):
    """Only reviewed accounting roles define a reconciliation; labels never assign roles."""
    groups = defaultdict(list)
    for fact in facts:
        if fact.get('financial_role'):
            key = identity({**fact, 'metric': '', 'definition': '', 'segment': ''}, fiscal_month)
            groups[key].append(fact)
    checks = []
    definitions = (
        ('balance_sheet', 'asset_total', ('liability_total', 'equity_total'), 1),
        ('cash_roll', 'closing_cash', ('opening_cash', 'net_cash_change'), 1),
        ('gross_to_net', 'net_revenue', ('gross_revenue', 'revenue_deduction'), -1),
        ('contribution', 'contribution', ('contribution_base', 'contribution_cost'), -1),
    )
    for members in groups.values():
        roles = defaultdict(list)
        for fact in members:
            roles[fact['financial_role']].append(fact)
        for name, total, components, sign in definitions:
            required = (total, *components)
            if not any(role in roles for role in required):
                continue
            missing = [role for role in required if role not in roles]
            ambiguous = [role for role in required if len(roles[role]) > 1 and role not in ('revenue_deduction', 'contribution_cost')]
            used = [fact for role in required for fact in roles[role]]
            costs = [fact for fact in used if fact['financial_role'] in ('revenue_deduction', 'contribution_cost')]
            boundaries = [label(fact.get('cost_boundary')) for fact in costs]
            duplicate_costs = costs and (not all(boundaries) or len(set(boundaries)) != len(boundaries))
            check = {'kind': name, 'inputs': [fact['id'] for fact in used], 'status': 'unresolved'}
            if missing or ambiguous or duplicate_costs:
                check['detail'] = f'{name}: missing roles {missing}; ambiguous roles {ambiguous}; cost boundaries must be explicit and disjoint.'
            elif any(numeric(fact.get('value')) is None for fact in used):
                check['detail'] = f'{name}: a mapped input is missing, never zero.'
            else:
                first = sum(numeric(fact['value']) for fact in roles[components[0]])
                second = sum(numeric(fact['value']) for fact in roles[components[1]])
                expected = first + sign * second
                observed = numeric(roles[total][0]['value'])
                places = len(str(roles[total][0]['value']).strip('()').partition('.')[2])
                check.update(expected=expected, observed=observed, status='pass' if abs(round(expected, places) - observed) <= 1e-9 else 'fail',
                             detail=f'{name}: reported {observed:g}; computed {expected:g}')
            checks.append(check)
    return checks


def baseline(fact_base):
    """Resolve only identical, fully scoped observations or an explicit reviewed choice."""
    review = fact_base.get('ledger_review', {})
    mappings = review.get('mappings', {})
    groups = defaultdict(list)
    raw_index = observations(fact_base)
    for original in raw_index.values():
        if original.get('value') in (None, '') and not original.get('cell_error'):
            continue
        fact = {**original, **mappings.get(original['id'], {})}
        groups[identity(fact, review.get('fiscal_year_end_month', 3))].append(fact)
    rows, exceptions = [], []
    for key, members in sorted(groups.items()):
        row_id = digest(key)
        chosen = review.get('selections', {}).get(row_id, {})
        values = {numeric(fact.get('value')) for fact in members}
        unsafe = [fact['id'] for fact in members if numeric(fact.get('value')) is None or
                  fact.get('cell_error') or fact.get('ambiguity') or fact.get('ocr_only') or
                  not all(label(fact.get(field)) for field in ('metric', 'unit', 'basis')) or
                  not fact.get('document') or not fact.get('location') or
                  fact.get('formula') and not fact.get('formula_verified')]
        selected = next((fact for fact in members if fact['id'] == chosen.get('source_id')), None)
        if selected and chosen.get('reason', '').strip() and selected['id'] not in unsafe and chosen.get('observation_sha256') == digest(raw_index[selected['id']]):
            winner, reason = selected, chosen['reason'].strip()
        elif not chosen and len(values) == 1 and not unsafe:
            winner, reason = min(members, key=lambda fact: fact['id']), 'Sources agree in the same metric, period and basis; stable source ID breaks the tie.'
        else:
            winner, reason = None, 'Review the conflicting values or supply missing definitions and verified inputs.'
        row = {'id': row_id, 'meaning': {field: (winner or members[0]).get(field, '') for field in (*DIMENSIONS, 'period', 'financial_role', 'cost_boundary')},
               'value': numeric(winner['value']) if winner else None, 'source_id': winner['id'] if winner else None,
               'reason': reason, 'conflict': len(values) > 1, 'status': 'resolved' if winner else 'unresolved',
               'candidates': [{'id': fact['id'], 'value': fact.get('value'), 'document': fact.get('document'),
                               'location': fact.get('location'), 'observation_sha256': digest(raw_index[fact['id']]),
                               'source_sha256': fact.get('provenance', {}).get('sha256') or fact.get('source_sha256'),
                               'source_hash_scope': 'original_document' if fact.get('provenance', {}).get('sha256') else fact.get('source_hash_scope'),
                               'unsafe': fact['id'] in unsafe} for fact in members]}
        rows.append(row)
        if not winner:
            exceptions.append({'kind': 'baseline', 'row': row_id, 'detail': f'{members[0].get("metric")}, {members[0].get("period")}: {reason}'})
    # Existing code-computed reconciliations remain authoritative; never override a failed check.
    for check in fact_base.get('checks', []):
        if check.get('status') in ('inconsistent', 'fail', 'not_computable'):
            exceptions.append({'kind': 'reconciliation', 'detail': check.get('question') or check.get('detail') or str(check)})
    versions = defaultdict(list)
    for row in rows:
        meaning = row['meaning']
        versions[tuple((key, label(value)) for key, value in meaning.items() if key not in ('version', 'financial_role', 'cost_boundary'))].append(row)
    for alternatives in versions.values():
        if len(alternatives) < 2 or len({row['meaning']['version'] for row in alternatives}) < 2:
            continue
        selected = [row for row in alternatives if row['id'] in review.get('selections', {}) and row['source_id']]
        for row in alternatives:
            if len(selected) != 1 or row is not selected[0]:
                row.update(value=None, source_id=None, status='alternative_version' if len(selected) == 1 else 'unresolved',
                           reason='Alternative versions remain separate; select one reviewed source version.')
        if len(selected) != 1:
            exceptions.append({'kind': 'version_selection', 'detail': f'{alternatives[0]["meaning"]["metric"]}: choose one source version with a recorded reason'})
    schedules = defaultdict(list)
    for row in rows:
        for candidate in row['candidates']:
            fact = raw_index[candidate['id']]
            table = fact.get('table') or {}
            if table:
                schedules[table['id']].append({'metric': row['meaning']['metric'], 'period': row['meaning']['period'],
                                              'basis': row['meaning']['basis'], 'value': row['value'], 'unit': row['meaning']['unit'],
                                              'baseline_row': row['id'], 'source_id': row['source_id'], 'status': row['status']})
    mapped = mapped_observations(fact_base)
    checks = reconciliations([mapped[key] for key in dict.fromkeys(row['source_id'] for row in rows if row['source_id'])], review.get('fiscal_year_end_month', 3))
    exceptions += [{'kind': 'reconciliation', 'detail': check['detail']} for check in checks if check['status'] != 'pass']
    return {'version': VERSION, 'rows': rows, 'exceptions': exceptions, 'schedules': dict(schedules), 'reconciliations': checks,
            'scope': 'Source observations only; missing statements are not reconstructed.'}


def canonical(fact_base):
    """Use one chosen value in each source-shaped schedule, retaining the winning locator."""
    result = copy.deepcopy(fact_base)
    index = mapped_observations(fact_base)
    choices = {candidate['id']: row for row in baseline(fact_base)['rows'] for candidate in row['candidates']}
    for collection in ('facts', 'workbook_cells'):
        kept = []
        for original in result.get(collection, []):
            fact = {**original, **fact_base.get('ledger_review', {}).get('mappings', {}).get(original['id'], {})}
            row = choices.get(fact['id'])
            if row:
                if not row['source_id']:
                    continue
                winner = index[row['source_id']]
                fact.update(value=winner['value'], document=winner.get('document'), location=winner.get('location'),
                            baseline_source_id=winner['id'], statement=winner.get('statement', fact.get('statement', '')))
            kept.append(fact)
        result[collection] = kept
    return result


def source(fact):
    return {'op': 'source', 'id': fact.get('baseline_source_id', fact['id'])}


def calculation(op, *inputs):
    return {'op': op, 'inputs': list(inputs)}


def constant(value, reason):
    return {'op': 'constant', 'value': value, 'reason': reason}


def evaluate(expression, index):
    op = expression['op']
    if op == 'source':
        value = numeric(index[expression['id']].get('value'))
        if value is None:
            raise ValueError('Input is missing or non-numeric')
        return value
    if op == 'constant':
        return expression['value']
    values = [evaluate(item, index) for item in expression['inputs']]
    if op == 'sum':
        return sum(values)
    if op == 'difference':
        return values[0] - values[1]
    if op == 'ratio_percent':
        return values[0] / values[1] * 100
    if op == 'growth_percent':
        return (values[0] / values[1] - 1) * 100
    if op == 'multiple':
        return values[0] / values[1]
    if op == 'product':
        return math.prod(values)
    if op == 'minimum':
        return min(values)
    if op == 'maximum':
        return max(values)
    if op == 'mean':
        return sum(values) / len(values)
    if op == 'median':
        values = sorted(values)
        middle = len(values) // 2
        return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    if op == 'count':
        return len(values)
    if op == 'annualised_percent':
        return (values[0] ** (1 / values[1]) - 1) * 100
    if op == 'runway_months':
        opening, floor, months, *flows = values
        complete = 0
        for flow in flows:
            if opening < floor or opening + flow < floor:
                break
            opening += flow
            complete += 1
        return complete * months
    raise ValueError(f'Unsupported calculation: {op}')


def inputs(expression):
    if expression['op'] == 'source':
        return [expression['id']]
    return list(dict.fromkeys(item for child in expression.get('inputs', []) for item in inputs(child)))


def _strings(page):
    """Only fields drawn by page_spec/deck_render; geometry and settings are not figures."""
    yield 'title', page.get('title') or page.get('brief', '')
    for n, text in enumerate(page.get('takeaways', [])):
        yield f'takeaways.{n}', text
    exhibits = page.get('exhibits', {})
    for n, kpi in enumerate(exhibits.get('kpis', [])):
        for field in ('label', 'value', 'sub'):
            yield f'kpis.{n}.{field}', str(kpi.get(field, ''))
    for kind in ('table', 'grid'):
        table = exhibits.get(kind, {})
        for n, text in enumerate(table.get('header', [])):
            yield f'{kind}.header.{n}', str(text)
        for r, row in enumerate(table.get('rows', [])):
            for c, text in enumerate(row):
                yield f'{kind}.rows.{r}.{c}', str(text)
    for kind in ('chart', 'chart2'):
        chart = exhibits.get(kind, {})
        for field in ('caption', 'note', 'unit'):
            yield f'{kind}.{field}', str(chart.get(field, ''))
        for n, text in enumerate(chart.get('categories', [])):
            yield f'{kind}.categories.{n}', str(text)
        for s, series in enumerate(chart.get('series', [])):
            yield f'{kind}.series.{s}.name', series['name']
            for n, value in enumerate(series['values']):
                places = chart.get('decimals', 0)
                yield f'{kind}.series.{s}.values.{n}', f'{value:.{places}f}'


def occurrences(page):
    for path, text in _strings(page):
        for n, match in enumerate(NUMBER.finditer(text)):
            token = match.group()
            meaning = None
            parts = path.split('.')
            if parts[0] in ('table', 'grid') and parts[1] == 'rows':
                table, r, c = page['exhibits'][parts[0]], int(parts[2]), int(parts[3])
                meaning = [table['rows'][r][0], table['header'][c], table['header'][0]]
            elif parts[0] == 'kpis':
                kpi = page['exhibits']['kpis'][int(parts[1])]
                meaning = [kpi['label'], kpi['sub'] if parts[-1] == 'value' else '']
            elif parts[0] in ('chart', 'chart2') and 'values' in parts:
                chart = page['exhibits'][parts[0]]
                meaning = [chart['series'][int(parts[2])]['name'], chart['categories'][int(parts[4])], chart.get('unit'), chart.get('caption')]
            yield {'slot': f'{path}#{n}', 'path': path, 'text': text, 'figure': token,
                   'value': numeric(token), 'context_sha256': digest([text[:match.start()] + '{}' + text[match.end():], meaning])}


def _meaning(page, occurrence):
    path = occurrence['path'].split('.')
    exhibits = page['exhibits']
    if path[0] in ('table', 'grid') and path[1] == 'rows':
        table, r, c = exhibits[path[0]], int(path[2]), int(path[3])
        return table['rows'][r][0], table['header'][c], c > 0
    if path[0] == 'kpis':
        kpi = exhibits['kpis'][int(path[1])]
        return kpi['label'], kpi.get('sub', ''), path[-1] == 'value'
    if path[0] in ('chart', 'chart2') and 'values' in path:
        chart, s, c = exhibits[path[0]], int(path[2]), int(path[4])
        return chart['series'][s]['name'], str(chart['categories'][c]).removesuffix(' (P)'), True
    return '', '', False


def _resolve(page, occurrence, facts):
    """Bind meaning before checking value: unrelated equal digits never establish lineage."""
    metric, period, data = _meaning(page, occurrence)
    if occurrence['path'] == 'title' and page.get('continuation'):
        continued = page['continuation']
        if occurrence['text'].endswith(f'({continued["index"]}/{continued["total"]})'):
            return {'op': 'navigation', 'figure': occurrence['figure']}
    family = page.get('family', page['key'])
    metric = label(metric.removesuffix(' — Total'))
    period = label(period)
    whole = [fact for fact in facts if label(fact.get('segment')) in ('', 'total', 'overall', 'all')]
    candidates = [fact for fact in whole if label(fact.get('metric')) == metric and
                  (not period or label(fact.get('period')) == period)] if data else []
    if data and family == 'snapshot':
        candidates = [fact for fact in whole if label(fact.get('metric')) == metric]
        from delivery.deal_documents.semantics import period_of
        dated = [(period_of(fact.get('period')), fact) for fact in candidates]
        dated = [(p, f) for p, f in dated if p]
        candidates = [max(dated, key=lambda item: item[0][1])[1]] if dated else []
    # Common-size and margin panels have an explicit named denominator.
    denominator = None
    if data and family == 'margins':
        denominator = page['exhibits'].get('table', {}).get('header', [''])[0].removeprefix('% of ')
    elif data and ' as % of ' in metric:
        metric, denominator = metric.split(' as % of ', 1)
    if denominator:
        tops = [f for f in whole if label(f.get('metric')) == metric and label(f.get('period')) == period]
        bottoms = [f for f in whole if label(f.get('metric')) == label(denominator) and label(f.get('period')) == period]
        if len(tops) == len(bottoms) == 1 and tops[0].get('unit') == bottoms[0].get('unit'):
            return calculation('ratio_percent', source(tops[0]), source(bottoms[0]))
        return None
    if len(candidates) == 1:
        return source(candidates[0])
    # A numeric part of a period, holder name or unit is a label, not an amount.
    for fact in facts:
        for field in ('period', 'segment', 'metric', 'unit', 'definition'):
            text = str(fact.get(field) or '')
            fragments = [text]
            if field == 'period':
                fragments += re.findall(r'\b(?:FY\s*\d{2,4}|[A-Za-z]{3}-\d{2,4})\b', text, re.I)
            for fragment in fragments:
                if fragment and fragment.casefold() in occurrence['text'].casefold() and any(
                        match.group() == occurrence['figure'] for match in NUMBER.finditer(fragment)):
                    return {'op': 'field', 'id': fact.get('baseline_source_id', fact['id']), 'field': field, 'figure': occurrence['figure']}
    quoted = [fact for fact in facts if (not data or family in ('risks', 'highlights', 'team', 'competition')) and
              len(occurrence['text'].split()) >= 3 and label(occurrence['text']) in label(fact.get('statement')) and
              occurrence['figure'] in str(fact.get('statement', ''))]
    if len(quoted) == 1:
        return {'op': 'field', 'id': quoted[0].get('baseline_source_id', quoted[0]['id']), 'field': 'statement', 'figure': occurrence['figure']}
    # A label or date is traced to its precise source field, never treated as an amount.
    if not data:
        field = 'period' if any(part in occurrence['path'] for part in ('header', 'categories', '.sub')) else None
        matches = [fact for fact in facts if field and occurrence['figure'] in str(fact.get(field, '')) and
                   label(fact.get(field)) and label(fact[field]) in label(occurrence['text'])]
        if matches:
            return {'op': 'field', 'id': matches[0].get('baseline_source_id', matches[0]['id']), 'field': field,
                    'figure': occurrence['figure']}
        # Authored figures require the metric, period and unit in their sentence.
        text = label(occurrence['text'])
        matches = [fact for fact in facts if label(fact.get('metric')) and label(fact['metric']) in text and
                   (not fact.get('period') or label(fact['period']) in text) and
                   (not fact.get('segment') or label(fact['segment']) in text) and
                   (not fact.get('unit') or label(fact['unit']) in text) and
                   numeric(fact.get('value')) == occurrence['value']]
        if len(matches) == 1:
            return source(matches[0])
    return None


def bind_pages(pages, fact_base):
    index = observations(canonical(fact_base))
    for page in pages:
        facts = [index[key] for key in page.get('cells', []) if key in index]
        slots = {}
        for item in occurrences(page):
            root, _, rest = item['slot'].partition('.')
            explicit = page.get('exhibits', {}).get(root, {})
            if root == 'kpis':
                n, _, rest = rest.partition('.')
                explicit = explicit[int(n)]
            expression = explicit.get('figure_expressions', {}).get(rest) or _resolve(page, item, facts)
            if expression:
                slots[item['slot']] = {'expression': expression, 'context_sha256': item['context_sha256']}
        page['figure_slots'] = slots
    return pages


def tie_out(documents, fact_base):
    canonical_base = baseline(fact_base)
    index = mapped_observations(fact_base)
    active = {candidate['id']: row['source_id'] for row in canonical_base['rows'] for candidate in row['candidates']}
    rows, exceptions, printed = [], list(canonical_base['exceptions']), defaultdict(list)
    scoped = canonical(fact_base)
    canonical_index = observations(scoped)
    for document, pages in documents.items():
        for number, page in enumerate(pages, 1):
            facts = [canonical_index[key] for key in page.get('cells', []) if key in canonical_index]
            facts += [fact for fact in scoped.get('facts', []) if fact.get('topic') in page.get('topics', []) and fact['id'] not in page.get('cells', [])]
            for item in occurrences(page):
                row = {**item, 'document': document, 'page': number + 2, 'content_page': number, 'page_key': page['key'], 'status': 'exception', 'sources': []}
                binding = page.get('figure_slots', {}).get(item['slot'])
                # Older cached pages are resolved afresh; no generation step is discarded on resume.
                expression = binding['expression'] if binding else _resolve(page, item, facts)
                try:
                    if binding and binding['context_sha256'] != item['context_sha256']:
                        raise ValueError('The printed label, period or unit changed after binding')
                    if not expression:
                        raise ValueError('No unambiguous source or supported calculation for this occurrence')
                    if expression['op'] == 'source':
                        row['expected'] = evaluate(expression, index)
                        meaning = dict(index[expression['id']])
                        visible = label(' '.join(text for _, text in _strings(page)))
                        for qualifier in ('definition', 'version'):
                            if label(meaning.get(qualifier)) not in visible:
                                meaning[qualifier] = ''
                        printed[identity(meaning)].append(row)
                    refs = inputs(expression) if expression['op'] != 'field' else [expression['id']]
                    row['expression'] = expression
                    for ref in refs:
                        fact = index[ref]
                        if ref in active and active[ref] != ref:
                            raise ValueError('Printed input is not the resolved baseline source or active version')
                        if fact.get('ocr_only') or fact.get('cell_error') or fact.get('ambiguity'):
                            raise ValueError('Source requires review of OCR, errors or ambiguous definitions')
                        row['sources'].append({'id': ref, 'document': fact.get('document'), 'location': fact.get('location'),
                                               'value': fact.get('value'), 'meaning': {key: fact.get(key) for key in (*DIMENSIONS, 'period')},
                                               'observation_sha256': digest(observations(fact_base)[ref]),
                                               'source_sha256': fact.get('provenance', {}).get('sha256') or fact.get('source_sha256'),
                                               'source_hash_scope': 'original_document' if fact.get('provenance', {}).get('sha256') else fact.get('source_hash_scope')})
                        if not fact.get('document') or not fact.get('location'):
                            raise ValueError('Source locator is missing')
                    if expression['op'] == 'navigation':
                        if item['figure'] != expression['figure']:
                            raise ValueError('Navigation numbering changed')
                        row['status'] = 'navigation'
                    elif expression['op'] == 'field':
                        if item['figure'] != expression['figure'] or item['figure'] not in str(index[expression['id']].get(expression['field'], '')):
                            raise ValueError('Printed source label differs')
                        row['status'] = 'source_label'
                    else:
                        expected = evaluate(expression, index)
                        places = len(item['figure'].strip('()').partition('.')[2])
                        if abs(expected - item['value']) > .5 * 10 ** -places + 1e-9:
                            raise ValueError(f'Printed {item["figure"]}; source/calculation requires {expected:g}')
                        row.update(status='tied', expected=expected)
                except (KeyError, ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
                    row['detail'] = str(exc)
                    exceptions.append({'kind': 'figure', 'document': document, 'page': number + 2, 'slot': item['slot'], 'detail': str(exc)})
                rows.append(row)
    for members in printed.values():
        # Compare recomputed values, so different display precision is not a false conflict.
        if len({item['expected'] for item in members}) > 1:
            exceptions.append({'kind': 'cross_document', 'detail': 'The same metric, period and basis has different printed values',
                               'occurrences': [{key: item[key] for key in ('document', 'page', 'slot', 'figure')} for item in members]})
    return {'version': VERSION, 'baseline': canonical_base, 'review': fact_base.get('ledger_review', {}), 'occurrences': rows, 'exceptions': exceptions,
            'affected_approvals': ['memo', 'decks'] if exceptions else [],
            'export_review': 'Structured pages checked. Export text and chart payload verification is required before release.'}


def audit_exports(report, documents, run_dir, source_lines):
    """Read the exact saved bytes. Unreadable or unmatched exported numbers fail closed."""
    report['exports'] = []
    structured_rows = list(report['occurrences'])
    missing_hashes = {source['id'] for row in report['occurrences'] for source in row['sources'] if not source.get('source_sha256')}
    for ref in sorted(missing_hashes):
        report['exceptions'].append({'kind': 'source_hash', 'detail': f'{ref}: source fingerprint unavailable; re-extract or independently review the original source'})
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
          'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
    normalized = lambda text: ' '.join(text.replace('\u2212', '-').split())
    for document, pages in documents.items():
        try:
            pptx = (run_dir / f'{document}.pptx').read_bytes()
            pdf = (run_dir / f'{document}.pdf').read_bytes()
            entry = {'document': document, 'pptx_sha256': hashlib.sha256(pptx).hexdigest(),
                     'pdf_sha256': hashlib.sha256(pdf).hexdigest(), 'status': 'checked'}
            with ZipFile(BytesIO(pptx)) as archive:
                slides = sorted((name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)),
                                key=lambda name: int(re.search(r'(\d+)\.xml', name)[1]))
                if len(slides) != len(pages) + 2:
                    raise ValueError('Exported page count differs from structured pages')
                pdf_expected = []
                for slide_number, name in enumerate(slides, 1):
                    root = ElementTree.fromstring(archive.read(name))
                    texts = [''.join(node.itertext()) for p in root.findall('.//a:p', ns) for node in [p] if node.findall('.//a:t', ns)]
                    # itertext includes only the text held by drawing paragraphs, not shape IDs.
                    tokens = Counter()
                    page = pages[slide_number - 3] if slide_number >= 3 else None
                    known = {normalized(text): path for path, text in _strings(page)} if page else {}
                    for p, text in enumerate(texts):
                        figures = list(NUMBER.finditer(text))
                        tokens.update(numeric(match.group()) for match in figures)
                        if not figures:
                            continue
                        if normalized(text) == str(slide_number):
                            status = 'navigation'
                        elif page is None:
                            status = 'document_frame_review'
                            report['exceptions'].append({'kind': 'document_frame', 'document': document, 'page': slide_number,
                                                         'detail': f'Confirm generated date or notice reference: {text}'})
                        elif normalized(text) in known:
                            status = 'structured_text'
                        elif source_lines.get((document, slide_number - 2), '') and normalized(text) in {
                                normalized(f'{note}  Source: {source_lines[(document, slide_number - 2)]}')
                                for note in ('Company-reported, not independently verified.', 'Includes public sources; not independently verified.')}:
                            status = 'source_locator'
                        else:
                            status = 'exception'
                            report['exceptions'].append({'kind': 'export_text', 'document': document, 'page': slide_number,
                                                         'detail': f'Exported numeric text has no exact structured match: {text}'})
                        for n, match in enumerate(figures):
                            linked = [row for row in structured_rows if row['document'] == document and row['page'] == slide_number and
                                      row['path'] == known.get(normalized(text)) and row['figure'] == match.group()]
                            report['occurrences'].append({'document': document, 'page': slide_number, 'slot': f'pptx.paragraph.{p}#{n}',
                                'figure': match.group(), 'status': status, 'sources': [source for row in linked for source in row['sources']],
                                'structured_slots': [row['slot'] for row in linked], 'structured_path': known.get(normalized(text))})
                    if page:
                        if any(chart.get('plot') == 'waterfall' for key in ('chart', 'chart2') if (chart := page['exhibits'].get(key))):
                            report['exceptions'].append({'kind': 'export_chart', 'document': document, 'page': slide_number,
                                                         'detail': 'Waterfall label and hidden-series layout requires visual review'})
                        # Charts are checked against their saved payloads below; PDF includes their labels.
                        for key in ('chart', 'chart2'):
                            chart = page['exhibits'].get(key)
                            if chart:
                                for _, text in _strings({'title': '', 'key': '', 'exhibits': {key: chart}}):
                                    tokens.update(numeric(m.group()) for m in NUMBER.finditer(text))
                    pdf_expected.append(tokens)
                expected_charts = [chart for page in pages for key in ('chart', 'chart2') if (chart := page['exhibits'].get(key)) and chart.get('plot') != 'waterfall']
                chart_files = sorted((name for name in archive.namelist() if re.fullmatch(r'ppt/charts/chart\d+\.xml', name)), key=lambda name: int(re.search(r'(\d+)\.xml', name)[1]))
                if len(chart_files) != len(expected_charts):
                    raise ValueError('Chart payload count differs or requires waterfall visual review')
                for name, chart in zip(chart_files, expected_charts):
                    root = ElementTree.fromstring(archive.read(name))
                    actual = [[numeric(node.text) for node in series.findall('.//c:val/c:numRef/c:numCache/c:pt/c:v', ns)] for series in root.findall('.//c:ser', ns)]
                    if actual != [series['values'] for series in chart['series']]:
                        raise ValueError(f'{name}: chart values differ from structured inputs')
                    for native, series in zip(root.findall('.//c:ser', ns), chart['series']):
                        categories = [node.text for node in native.findall('.//c:cat/c:strRef/c:strCache/c:pt/c:v', ns)]
                        names = [node.text for node in native.findall('.//c:tx/c:strRef/c:strCache/c:pt/c:v', ns)]
                        if categories != list(map(str, chart['categories'])) or names != [series['name']]:
                            raise ValueError(f'{name}: chart labels differ from structured inputs')
            from pypdf import PdfReader
            extracted = PdfReader(BytesIO(pdf)).pages
            if len(extracted) != len(pdf_expected):
                raise ValueError('PDF page count differs from editable export')
            for n, (page, allowed) in enumerate(zip(extracted, pdf_expected), 1):
                text = page.extract_text() or ''
                if not text.strip():
                    raise ValueError(f'PDF page {n}: no extractable text; visual review required')
                for token, count in Counter(numeric(m.group()) for m in NUMBER.finditer(text)).items():
                    if count > allowed[token]:
                        raise ValueError(f'PDF page {n}: unmatched number {token}; visual review required')
                for token_number, match in enumerate(NUMBER.finditer(text)):
                    linked = [row for row in structured_rows if row['document'] == document and row['page'] == n and row['value'] == numeric(match.group())]
                    report['occurrences'].append({'document': document, 'page': n, 'slot': f'pdf.text#{token_number}',
                        'figure': match.group(), 'status': 'export_text_match' if len(linked) <= 1 else 'visual_review_required',
                        'sources': [source for row in linked for source in row['sources']], 'structured_slots': [row['slot'] for row in linked]})
                    if len(linked) > 1:
                        report['exceptions'].append({'kind': 'visual_review', 'document': document, 'page': n,
                            'detail': f'PDF occurrence {token_number} ({match.group()}) has multiple possible structured locations; verify its placement'})
                if n >= 3:
                    structured = pages[n - 3]
                    for kind in ('table', 'grid'):
                        for row in structured['exhibits'].get(kind, {}).get('rows', []):
                            if any(NUMBER.search(str(cell)) for cell in row) and normalized(' '.join(row)) not in normalized(text):
                                raise ValueError(f'PDF page {n}: row label and figures could not be reconciled in reading order; visual review required')
                    if any(key in structured['exhibits'] for key in ('chart', 'chart2')):
                        report['exceptions'].append({'kind': 'visual_review', 'document': document, 'page': n,
                            'detail': 'Chart payload is checked in the editable file; PDF label placement requires visual review'})
            report['exports'].append(entry)
        except Exception as exc:
            # Third-party PDF/ZIP parsers raise several exception classes; a parser failure never approves an export.
            report['exceptions'].append({'kind': 'export_review', 'document': document, 'detail': f'Export verification incomplete: {type(exc).__name__}: {exc}'})
    report['export_review'] = 'Exact exported bytes checked where readable. Any unresolved text, chart or visual review appears in exceptions.'
    report['affected_approvals'] = ['memo', 'decks'] if report['exceptions'] else []
    return report


def gate_section(report):
    return {'section': 'number_tie_out', 'title': 'Financial baseline and numerical tie-out', 'paragraphs': [],
            'problems': [f'{item["kind"]}: {item["detail"]}' for item in report['exceptions']] +
                        ([] if 'exports' in report else ['Export verification is pending; rendered bytes must be checked before release.'])}


def markdown(report):
    lines = ['# Source ledger (draft)', '', report['export_review'], '',
             f'{len(report["occurrences"])} numerical occurrences; {len(report["exceptions"])} exceptions.', '',
             '| Document / page | Location | Figure | Result | Source / workings |', '|---|---|---|---|---|']
    for row in report['occurrences']:
        sources = '; '.join(f'{s["id"]}: {s["document"]}, {s["location"]}' for s in row['sources'])
        cells = [f'{row["document"]} / {row["page"]}', row['slot'], row['figure'], row['status'],
                 row.get('detail') or json.dumps(row.get('expression', {})) + ' ' + sources]
        lines.append('| ' + ' | '.join(str(cell).replace('|', '\\|').replace('\n', ' ') for cell in cells) + ' |')
    lines += ['', '## Exceptions', ''] + [f'- {item["kind"]}: {item["detail"]}' for item in report['exceptions']]
    return '\n'.join(lines) + '\n'
