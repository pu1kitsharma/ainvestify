"""Seeded differential test: random synthetic formulas, pure-Python engine vs isolated LibreOffice."""
import random

import pytest

from agents.tools import recalc
from tests.tools.synthetic_books import build

available, reason = recalc.availability()
pytestmark = pytest.mark.skipif(not available, reason=f'isolated LibreOffice unavailable: {reason}')

FUNCS1 = ['ABS({})', 'ROUND({},1)', 'ROUND({},0)', 'IF({}>5,{},-{})', 'IFERROR(1/({}-5),99)', 'MAX({},3)', 'MIN({},3)', '({})^2',
          'SQRT(ABS({}))', 'ROUNDDOWN({},1)', 'ROUNDUP({},1)', 'INT({})', 'MOD(ABS({}),4)', 'SIGN({}-5)', 'IF(AND({}>2,{}<8),1,0)']
FUNCS_RANGE = ['SUM({r})', 'AVERAGE({r})', 'MIN({r})', 'MAX({r})', 'COUNT({r})', 'SUMPRODUCT({r},{r})', 'MEDIAN({r})', 'COUNTIF({r},">4")',
               'SUMIF({r},">=3")', 'INDEX({r},2)', 'MATCH(5,{r},0)', 'IFERROR(MATCH(5,{r},0),0)', 'NPV(0.1,{r})', 'IFERROR(IRR({r}),-9)']


def make_cells(rng):
    cells = {}
    for r in range(1, 9):
        for c in 'ABCD':
            cells[f'{c}{r}'] = round(rng.uniform(-4, 12), 2) if rng.random() > 0.1 else None
    cells = {k: v for k, v in cells.items() if v is not None}
    cells['A1'], cells['B2'] = 5, 5
    formulas = {}
    for i in range(1, 161):
        col = rng.choice('ABCD')
        row = rng.randint(1, 8)
        ref = f'{col}{row}'
        kind = rng.random()
        if kind < .35:
            f = rng.choice(FUNCS1).format(*[ref] * 3)
        elif kind < .65:
            c1 = rng.choice('ABCD')
            f = rng.choice(FUNCS_RANGE).format(r=f'{c1}1:{c1}{rng.randint(3, 8)}')
        elif kind < .85:
            o = rng.choice('+-*/')
            f = f'{ref}{o}{rng.choice("ABCD")}{rng.randint(1, 8)}'
            if rng.random() < .3:
                f = f'({f})*{rng.choice(["1.1", "0.5", "2"])}-{rng.choice("ABCD")}{rng.randint(1, 8)}'
        else:
            f = f'IF({ref}>{rng.randint(0, 8)},{rng.choice("ABCD")}{rng.randint(1, 8)}*2,{rng.choice("ABCD")}{rng.randint(1, 8)}/2)'
        formulas[f'F{i}'] = '=' + f
    return {**cells, **formulas}


def test_random_formulas_agree_with_libreoffice():
    rng = random.Random(20261020)
    report = recalc.compare_libreoffice_to_engine(build({'D': make_cells(rng)}), timeout=180)
    assert report['status'] == 'compared'
    assert report['compared_cells'] == 160
    assert report['agreement'] >= 0.99, report['mismatches'][:5]
