import json
from pathlib import Path

import pytest

from scripts import validate_gold_scorer as vgs
from training import gold_adapter as ga
from training.envs import evaluate

FIXTURE = Path(__file__).parent / 'fixtures' / 'synth'
PRIVATE = Path(__file__).resolve().parents[2] / 'evals/agentic_banker/gold'


@pytest.fixture(scope='module')
def gold():
    return ga.load_gold(FIXTURE)


def checks(report):
    return {(c['environment'], n): r for c in report['cases'] for n, r in c['checks'].items()}


def test_key_structure_and_trap_handling(gold):
    keys = {k['environment']: k for k in ga.build_answer_keys(gold, 'd')}
    assert set(keys) == {'E1', 'E2', 'E4', 'E5', 'E6'}
    assert keys['E4']['checks']['flags']['expected'] == ['F-001', 'F-002', 'F-003']  # F-004 not flag-class
    assert ga.forbidden_ids(gold) == ['T-001', 'T-002']                              # flag_low_at_most excluded
    assert len(keys['E1']['checks']['historical_cells']['expected']) == 2           # actual numeric only
    assert len(keys['E2']['checks']['reported_totals']['expected']) == 1
    assert keys['E5']['checks']['cash_need']['expected'] == 42.0
    assert keys['E6']['checks']['text_cell_agreement']['expected'] == ['overview|deck.p1.rev.FY23', 'overview|deck.p1.total_cost.FY23']
    assert keys['E6']['checks']['sections']['expected'] == ['1|overview', '2|risks']


def test_oracle_is_max_and_unsupported_reported(gold):
    keys = ga.build_answer_keys(gold, 'd')
    rep = evaluate(ga.build_oracle(gold, 'd', keys), keys)
    c = checks(rep)
    for k, v in c.items():
        if keys_status(keys, k) == 'available':
            assert v['reward'] == 1.0 and v['status'] == 'matched'
        else:
            assert v['reward'] == 0.0 and v['status'] == 'unsupported'
    assert any(v['status'] == 'unsupported' for v in c.values())
    assert rep['mean_reward'] < 1.0  # unsupported dimensions are never hidden


def keys_status(keys, k):
    return next(x for x in keys if x['environment'] == k[0])['checks'][k[1]]['status']


@pytest.mark.parametrize('kind', ga.DEGRADATIONS)
def test_degraded_is_strictly_lower_with_specific_penalty(gold, kind):
    keys = ga.build_answer_keys(gold, 'd')
    oracle = evaluate(ga.build_oracle(gold, 'd', keys), keys)
    bad = evaluate(ga.degrade(gold, 'd', kind), keys)
    assert bad['mean_reward'] < oracle['mean_reward']
    effects = ga.expected_effects(gold, kind)
    assert effects
    c = checks(bad)
    for env, name, metric, pred in effects:
        v = c[(env, name)][metric]
        assert (v < 1.0) if pred == 'lt' else (v == 1.0)


def test_trap_flag_hits_precision_not_recall_and_miss_hits_recall(gold):
    keys = ga.build_answer_keys(gold, 'd')
    fp = checks(evaluate(ga.degrade(gold, 'd', 'flag_traps'), keys))[('E4', 'flags')]
    miss = checks(evaluate(ga.degrade(gold, 'd', 'miss_findings'), keys))[('E4', 'flags')]
    assert fp['precision'] < 1 and fp['recall'] == 1
    assert miss['recall'] < 1 and miss['precision'] == 1


def test_units_error_fails_numeric_and_set(gold):
    keys = ga.build_answer_keys(gold, 'd')
    c = checks(evaluate(ga.degrade(gold, 'd', 'wrong_units'), keys))
    assert c[('E1', 'historical_cells')]['reward'] == 0.0
    cash = checks(evaluate(ga.degrade(gold, 'd', 'wrong_cash_scale'), keys))
    assert cash[('E5', 'cash_need')]['status'] == 'mismatch'


def test_gap_report_counts(gold):
    g = ga.gap_report(gold)
    assert g['findings_not_flag_class_unscored'] == 1
    assert g['traps_low_severity_allowance_not_expressible'] == 1
    assert g['facts_company_projection_no_env_key_E3'] == 1
    assert g['facts_non_numeric_unscored'] == 1
    assert g['section_fact_refs_unresolved_to_fact_ids'] == 1


def test_validator_passes_on_fixture(tmp_path, capsys):
    root = tmp_path / 'gold'
    (root / 'one').mkdir(parents=True)
    for f in FIXTURE.iterdir():
        (root / 'one' / f.name).write_text(f.read_text())
    assert vgs.main(['--gold-root', str(root), '--out', str(tmp_path / 'r.json')]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['gold_sets_found'] == 1 and out['summary'][0]['deal'] == 'deal_a'
    assert out['summary'][0]['checks_failed'] == 0
    assert 'Fictional' not in json.dumps(out)


@pytest.mark.skipif(not (PRIVATE / 'toffee' / 'expected_findings.json').exists(), reason='private gold absent')
def test_private_gold_structure_and_counts_only(tmp_path):
    results = []
    for d in sorted(p for p in PRIVATE.iterdir() if p.is_dir() and not p.name.startswith('_')):
        r = vgs.validate(d, 'deal_x')
        results.append(r)
        assert all(c['passed'] for c in r['checks'])
        assert r['counts']['findings'] > 0 and r['counts']['traps'] > 0
        assert r['counts']['unsupported_dimensions'] > 0
    assert len(results) >= 1
