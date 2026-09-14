from decimal import Decimal
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from agents.company_metrics import MonthlyUpdate, metrics_report


def row(month, **kwargs):
    return dict(id=month,month=month,currency='INR',source_note='Monthly finance report',**kwargs)


def test_calculations_are_period_based_and_keep_input_records():
    report=metrics_report([row('2025-01',revenue='100'),row('2025-02',revenue='150',direct_costs='180',cash='120',net_burn='10',gmv='500',orders=5)])
    metrics={m['name']:m for m in report['calculations']}
    assert metrics['Revenue change from prior month']['value']=='50.00'
    assert metrics['Revenue change from prior month']['inputs']==['2025-01','2025-02']
    assert metrics['Delivery contribution']['value']=='-30.00'
    assert metrics['Delivery contribution margin']['value']=='-20.00'
    assert metrics['Cash coverage']['value']=='12.00'
    assert metrics['Average completed order value']['value']=='100.00'


@pytest.mark.parametrize('patch',[{'revenue':True},{'revenue':'NaN'},{'cash':-1},{'orders':2.2},{'orders':True},{'month':'2025-13'},{'month':'2099-01'}])
def test_invalid_actuals_rejected(patch):
    data=dict(month='2025-01',currency='INR',source_note='Monthly finance report',revenue='100')
    data.update(patch)
    with pytest.raises(ValidationError):MonthlyUpdate(**data)


@pytest.mark.parametrize('prior,latest',[('2025-01','2025-03'),('2025-02','2025-02')])
def test_nonconsecutive_periods_do_not_create_growth(prior,latest):
    report=metrics_report([row(prior,revenue=100),row(latest,revenue=150)])
    assert not any(c['name']=='Revenue change from prior month' for c in report['calculations'])


def test_currency_mismatch_zero_baseline_and_missing_are_not_guessed():
    for earlier in [row('2025-01',revenue=0),dict(row('2025-01',revenue=100),currency='USD')]:
        report=metrics_report([earlier,row('2025-02',revenue=150,net_burn=0,cash=10)])
        assert report['calculations']==[]
    assert metrics_report([])['calculations']==[]
    assert metrics_report([row('2025-01',revenue=0,direct_costs=10)])['calculations'][0]['value']=='-10.00'


def test_metric_update_scoping_revision_corrections_and_brief_invalidation(tmp_path):
    from store import Store
    from tests.test_operating_workflow import company
    from tests.test_company_brief import BriefModel
    from agents.company_brief import prepare_company_brief,brief_current
    from api.routers.operations import save_metrics,MetricUpdateRequest,download_metrics
    from fastapi import HTTPException
    with Store(tmp_path/'db') as store:
        lead=company(store);w=prepare_company_brief(store,lead,BriefModel())
        body=MetricUpdateRequest(expected_revision=w.revision,update=MonthlyUpdate(month='2025-01',currency='INR',source_note='Founder monthly statement',revenue='100'))
        with pytest.raises(HTTPException) as wrong:save_metrics(w.id,body,store,'other')
        assert wrong.value.status_code==404
        updated=save_metrics(w.id,body,store,'one')
        assert not brief_current(updated)
        assert updated.metrics['months'][0]['revenue']=='100'
        with pytest.raises(HTTPException) as conflict:save_metrics(w.id,body,store,'one')
        assert conflict.value.status_code==409
        body.expected_revision=updated.revision;body.update.revenue=Decimal('150')
        updated=save_metrics(w.id,body,store,'one')
        assert len(updated.metric_updates)==2
        assert len(updated.metrics['months'])==1
        assert updated.metrics['months'][0]['revenue']=='150'
        assert 'Founder monthly statement' in download_metrics(w.id,store,'one').body.decode()
        assert not updated.capabilities['external_sending']
