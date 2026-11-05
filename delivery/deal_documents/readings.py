"""Readings: every figure and comparison a writer may use, computed by code before any writing.

Writers place a reading's id, for example {c4}, inside their own sentence and code
prints the value. They type no period figure, so they cannot invent one or attach
it to the wrong period, and semantics.compute refuses comparisons of unlike periods
before a writer ever sees them.
"""
from __future__ import annotations

from itertools import combinations

from delivery.deal_documents.semantics import CalculationError, compute

LATEST_COLUMNS = 2  # shares and segment figures: the periods a reader compares first
LARGE_RISE = 200  # per cent


def headline_row(row):
    return ' — ' not in row['label'] or row['label'].endswith('— Total')


def _negative(fact):
    return str(fact.get('value', '')).strip().startswith(('(', '-'))


def build(tables, index):
    """{id: compute() result} for `tables`, in table order. Comparisons compute() refuses are simply absent."""
    results = {}

    def add(kind, decimals=1, **fields):
        calc = {'id': f'c{len(results) + 1}', 'kind': kind, 'a': '', 'b': '', 'rate': '', 'parts': [], 'decimals': decimals, **fields}
        try:
            results[calc['id']] = compute(calc, index)
        except (CalculationError, ValueError):
            pass

    for table in tables.values():
        columns = sorted(table['columns'])
        rows = [table['rows'][number] for number in sorted(table['rows'])]
        for row in rows:
            cells = [row['cells'][column] for column in columns if column in row['cells'] and row['cells'][column]['id'] in index]
            headline = headline_row(row)
            for cell in cells if headline else cells[-LATEST_COLUMNS:]:
                add('figure', parts=[cell['id']])
            if headline:
                for earlier, later in combinations(cells, 2):
                    add('growth', a=earlier['id'], b=later['id'])
                    add('difference', a=later['id'], b=earlier['id'], decimals=2)  # the only comparison of negative figures
        for column in columns[-LATEST_COLUMNS:]:
            cells = [row['cells'][column] for row in rows if headline_row(row) and column in row['cells'] and row['cells'][column]['id'] in index]
            for one, other in combinations(cells, 2):
                add('share', a=one['id'], b=other['id'])
                add('share', a=other['id'], b=one['id'])
    def useful(result):
        if result['kind'] == 'share':
            return 0 < result['value'] < 100
        return result['kind'] != 'difference' or any(_negative(index[fact_id]) for fact_id in result['facts'])
    kept = {key: result for key, result in results.items() if useful(result)}
    # "+4,100.0%" is how a spreadsheet prints a large rise; an investor reads it as a multiple.
    return {key: {**result, 'text': f'{1 + result["value"] / 100:.1f}x'} if result['kind'] == 'growth' and result['value'] > LARGE_RISE else result for key, result in kept.items()}


def standouts(results, index, limit=6):
    """The largest reported move in each whole-company measure, largest first: what a reader looks for before anything else."""
    def whole(result):
        return all(str(index[item].get('segment', '')).strip().lower() in ('', 'total', 'overall', 'all') for item in result['facts'])
    moves = {}
    for key, result in results.items():
        if result['kind'] == 'growth' and result['over_time'] and not result['projection'] and whole(result):
            measure = result['label'].split(' from ')[0]
            if measure not in moves or abs(result['value']) > abs(moves[measure][1]['value']):
                moves[measure] = (key, result)
    return dict(sorted(moves.values(), key=lambda item: -abs(item[1]['value']))[:limit])


def lines(results):
    return [f'{{{key}}} {result["label"].removeprefix("figures: ").replace(" (Total)", "").replace(" Current", "")} = {result["text"]}' for key, result in results.items()]


def relations(results):
    """Which of two measures grew faster over the same span, in words, so a reader need not divide to see what became a smaller share."""
    moves = [result for result in results.values() if result['kind'] == 'growth' and result['over_time']]
    found = []
    for one, other in combinations(moves, 2):
        measure, span = one['label'].split(' from ')[0], one['label'].split(' from ')[-1]
        rival, rival_span = other['label'].split(' from ')[0], other['label'].split(' from ')[-1]
        if span != rival_span or measure == rival or one['value'] == other['value']:
            continue
        fast, slow = ((measure, one), (rival, other)) if one['value'] > other['value'] else ((rival, other), (measure, one))
        found.append(f'{fast[0]} ({fast[1]["text"]}) grew faster than {slow[0]} ({slow[1]["text"]}), so {slow[0]} fell as a share of {fast[0]}.')
    return list(dict.fromkeys(found))
