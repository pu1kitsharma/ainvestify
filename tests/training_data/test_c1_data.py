import json
import pytest

from training.data import build_corpus, collectors, source_registry, taxonomy, xbrl_tasks
from training.envs.scoring import evaluate


@pytest.fixture(scope='module')
def corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp('c1') / 'run'
    m = build_corpus.build(build_corpus.load_fixtures(), out, plumbing_only=True)
    tasks = [json.loads(l) for l in (out / 'tasks.jsonl').read_text().splitlines()]
    keys = [json.loads(l) for l in (out / 'keys.jsonl').read_text().splitlines()]
    return m, tasks, keys, out


def test_registry_defaults_disabled():
    assert json.loads(source_registry.ENABLED_FILE.read_text()) == []
    assert all(s['rights_status'] == 'pending_review' for s in source_registry.SOURCES.values())
    assert not source_registry.is_enabled('sec_edgar_companyfacts')


def test_enable_list_rejects_unknown(tmp_path):
    p = tmp_path / 'e.json'
    p.write_text('["nope"]')
    with pytest.raises(ValueError):
        source_registry.enabled_ids(p)


def test_collector_refuses_without_enable_or_contact(tmp_path):
    calls = []
    c = collectors.EdgarCollector(tmp_path, environ={'RESEARCH_AGENT_CONTACT': 'Org a@b.co'}, opener=lambda r: calls.append(r))
    with pytest.raises(collectors.SourceDisabledError):
        c.companyfacts(1)
    en = tmp_path / 'en.json'
    en.write_text('["sec_edgar_companyfacts"]')
    c = collectors.EdgarCollector(tmp_path, environ={}, enabled_path=en, opener=lambda r: calls.append(r))
    with pytest.raises(collectors.SourceDisabledError):
        c.companyfacts(1)
    assert calls == []


def test_collector_caches_and_sends_only_env_contact(tmp_path):
    en = tmp_path / 'en.json'
    en.write_text('["sec_edgar_companyfacts"]')
    seen, sleeps = [], []
    c = collectors.EdgarCollector(tmp_path / 'cache', environ={'RESEARCH_AGENT_CONTACT': 'TestOrg t@example.org'}, enabled_path=en,
                                  opener=lambda r: seen.append(r) or b'{"cik": 1}', clock=lambda: 0.0, sleeper=sleeps.append)
    data, digest = c.companyfacts(1)
    c.companyfacts(2)
    assert data == {'cik': 1} and (tmp_path / 'cache' / (digest + '.json')).exists()
    assert seen[0].get_header('User-agent') == 'TestOrg t@example.org'
    assert sleeps and sleeps[0] >= 0.2  # <= 5 req/s
    assert len((tmp_path / 'cache' / 'index.jsonl').read_text().splitlines()) == 2


def test_sebi_fetcher_off(tmp_path):
    with pytest.raises(collectors.SourceDisabledError):
        collectors.SebiDocumentFetcher().fetch('https://example.invalid/x.pdf')
    en = tmp_path / 'en.json'
    en.write_text('["sebi_drhp_rhp_index"]')
    with pytest.raises(NotImplementedError):
        collectors.SebiDocumentFetcher(en).fetch('https://example.invalid/x.pdf')


def test_taxonomy():
    assert taxonomy.resolve_tag('CostOfRevenue') == 'cogs'
    assert taxonomy.resolve_label('Profit After Tax') == 'net_income'
    assert taxonomy.resolve_label('Finance costs') == 'interest_expense'
    assert taxonomy.resolve_tag('Unknown') is None
    assert taxonomy.parse_amount('Rs. 1,234.5 crore')[0] == 1234.5e7
    assert taxonomy.parse_amount('(12) lakh')[0] == -12e5
    with pytest.raises(ValueError):
        taxonomy.parse_amount('12 widgets')
    assert taxonomy.fiscal_year_label('2024-03-31') == 'FY2024'


def test_annual_series_ignores_quarterlies():
    facts, meta = build_corpus.load_fixtures()[1]
    s = xbrl_tasks.annual_series(facts)
    assert xbrl_tasks.fye_month(s) == 9
    assert len(s['revenue']) == 5 and all(e[5:7] == '09' for e in s['revenue'])


def test_perfect_answers_score_one_and_empty_score_zero(corpus):
    _, tasks, keys, _ = corpus
    preds = []
    for k in keys:
        obs = {n: {'status': 'observed', 'value': c['expected']} for n, c in k['checks'].items() if c['status'] == 'available'}
        preds.append({'case_id': k['case_id'], 'environment': k['environment'], 'observations': obs})
    report = evaluate(preds, keys)
    assert all(c['checks'][n]['status'] in ('matched', 'unsupported') for c in report['cases'] for n in c['checks'])
    zero = evaluate([], keys)
    assert zero['mean_reward'] == 0.0


def test_e4_injection_flags_match_and_controls_empty(corpus):
    _, tasks, keys, _ = corpus
    e4 = {k['case_id']: k['checks']['flags']['expected'] for k in keys if k['environment'] == 'E4'}
    assert any(v == [] for v in e4.values())
    seen = set()
    for cid, v in e4.items():
        assert len(v) <= 1
        seen.update(v)
        assert cid.endswith('-none') == (v == [])
        if v:
            assert cid.endswith('-' + v[0])
    assert seen == set(xbrl_tasks.INJECTIONS)
    # FY/CY mix only applies to non-December fiscal years
    assert not any('synthetic-saas' in c and c.endswith('fy_cy_mix') for c in e4)
    assert any('synthetic-hardware' in c and c.endswith('fy_cy_mix') for c in e4)


def test_e4_injection_actually_changes_package(corpus):
    _, tasks, _, _ = corpus
    t_none = next(t for t in tasks if t['case_id'] == 'E4-synthetic-saas-2022-12-31-none')
    t_sum = next(t for t in tasks if t['case_id'] == 'E4-synthetic-saas-2022-12-31-sum_ne_total')
    def gp(t): return [l['value'] for l in t['input']['package']['lines'] if l['item'] == 'gross_profit' and l['period_end'] == '2022-12-31'][0]
    def rc(t, e): return {l['item']: l['value'] for l in t['input']['package']['lines'] if l['statement'] == 'income' and l['period_end'] == e}
    c = rc(t_none, '2022-12-31')
    assert c['revenue'] - c['cogs'] == c['gross_profit']
    d = rc(t_sum, '2022-12-31')
    assert d['revenue'] - d['cogs'] != d['gross_profit']


def test_e3_key_is_next_year_and_history_excludes_it(corpus):
    _, tasks, keys, _ = corpus
    t = next(t for t in tasks if t['environment'] == 'E3')
    k = next(k for k in keys if k['case_id'] == t['case_id'])
    assert t['input']['forecast_period_end'] not in [h['period_end'] for h in t['input']['history']]
    assert 'future_actuals' not in json.dumps(t)
    c = k['checks']['future_actuals']
    assert c['absolute_tolerance'] == pytest.approx(0.1 * c['expected'], rel=1e-6)
    assert k['checks']['scenarios']['status'] == 'unsupported'


def test_e1_rebuild_cells_respect_scale(corpus):
    _, tasks, keys, _ = corpus
    for t in tasks:
        if t['environment'] != 'E1':
            continue
        k = next(k for k in keys if k['case_id'] == t['case_id'])
        exp = set(k['checks']['historical_cells']['expected'])
        got = {'%s|%s|%d' % (r['label'], r['period_end'], round(r['displayed_value'] * r['scale'])) for r in t['input']['rows']}
        assert exp == got


def test_e5_arithmetic(corpus):
    _, tasks, keys, _ = corpus
    for t in (t for t in tasks if t['environment'] == 'E5'):
        i = t['input']
        k = next(k for k in keys if k['case_id'] == t['case_id'])['checks']
        need = max(0.0, i['monthly_burn'] * i['horizon_months'] - i['opening_cash'])
        assert k['cash_need']['expected'] == pytest.approx(need, abs=0.01)
        assert k['maximum_draw']['expected'] == pytest.approx(need * (1 + i['buffer_pct_of_need']), abs=0.02)


def test_e7_cagr(corpus):
    _, tasks, keys, _ = corpus
    for t in (t for t in tasks if t['environment'] == 'E7'):
        k = next(k for k in keys if k['case_id'] == t['case_id'])['checks']
        f = dict(x.split('=') for x in k['source_figures']['expected'])
        assert k['cagr']['expected'] == pytest.approx((float(f['end']) / float(f['start'])) ** (1 / int(f['years'])) - 1, abs=1e-5)
        assert t['synthetic_figures']


def test_no_keys_leak_into_tasks(corpus):
    _, tasks, keys, out = corpus
    assert not any('checks' in t or 'expected' in json.dumps(t) for t in tasks)
    assert oct((out / 'keys.jsonl').stat().st_mode & 0o777) == '0o600'


def test_split_and_manifest(corpus):
    m, tasks, _, _ = corpus
    assert m['plumbing_only'] and m['split_validation']['coverage_thresholds_met'] is False
    assert set(m['counts_by_split']) == {'train', 'valid', 'test'}
    cov = m['coverage_vs_gate']
    assert cov['real_rights_approved'] == {'companies': 0, 'evidence_families': 0, 'sectors': 0} and not cov['gate_met']
    assert cov['shortfall']['companies'] == 20
    sec_split = {}
    for t in tasks:
        assert sec_split.setdefault(t['sector'], t['split']) == t['split']


def test_synthetic_not_approved_without_plumbing(tmp_path):
    m = build_corpus.build(build_corpus.load_fixtures(), tmp_path / 'o')
    assert m['split_validation'] is None and not m['plumbing_only']


def test_build_refuses_overwrite_and_few_sectors(corpus, tmp_path):
    with pytest.raises(FileExistsError):
        build_corpus.build(build_corpus.load_fixtures(), corpus[3])
    with pytest.raises(ValueError):
        build_corpus.build(build_corpus.load_fixtures()[:2], tmp_path / 'x')
