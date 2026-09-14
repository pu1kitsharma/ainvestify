import json
import pytest
from fastapi import BackgroundTasks, HTTPException
from agents.metric_extraction import ExtractedUpdate, extract_metric_update
from agents.company_metrics import metrics_report

TEXT='Hotel Example monthly actuals. Currency: INR.\nJanuary 2025\nRevenue: 1 lakh\nDirect variable costs: 60,000\nCash at month end: 200,000\nNet operating cash burn: 20,000\nFebruary 2025\nRevenue: 1.2 lakh\nGMV: 8 lakh\nCompleted orders: 40'


def model_result():
    return dict(months=[dict(month='2025-01',period_quote='January 2025',currency='INR',currency_quote='Currency: INR.',observations=[dict(field='revenue',quote='Revenue: 1 lakh',number_text='1 lakh'),dict(field='direct_costs',quote='Direct variable costs: 60,000',number_text='60,000'),dict(field='cash',quote='Cash at month end: 200,000',number_text='200,000'),dict(field='net_burn',quote='Net operating cash burn: 20,000',number_text='20,000')]),dict(month='2025-02',period_quote='February 2025',currency='INR',currency_quote='Currency: INR.',observations=[dict(field='revenue',quote='Revenue: 1.2 lakh',number_text='1.2 lakh'),dict(field='gmv',quote='GMV: 8 lakh',number_text='8 lakh'),dict(field='orders',quote='Completed orders: 40',number_text='40')])],issues=[])


class ExtractionModel:
    name='fixture'
    def __init__(self,result=None):self.result=result or model_result()
    def generate(self,instruction,payload,schema):
        self.input=json.loads(payload)
        blocks=self.input['source_blocks']
        def block_for(quote):
            matches=[key for key,value in blocks.items() if quote in value]
            return matches[0] if matches else 'UNKNOWN'
        months=[dict(period_source_id=block_for(r['period_quote']),currency_source_id=block_for(r['currency_quote']),observations=[dict(field=o['field'],source_id=block_for(o['quote'])) for o in r['observations']]) for r in self.result['months']]
        return schema(months=months,issues=self.result['issues'])


def test_ai_extracts_literal_values_code_normalizes_and_calculates():
    model=ExtractionModel()
    result=extract_metric_update(TEXT,'Founder monthly report','Hotel Example',model)
    assert result['issues']==[]
    assert len(result['updates'])==2
    assert result['updates'][0]['revenue']=='100000'
    assert result['updates'][1]['gmv']=='800000'
    assert result['updates'][0]['citations']['revenue']['quote']=='Revenue: 1 lakh'
    report=metrics_report([dict(r,id=str(i)) for i,r in enumerate(result['updates'])])
    growth=next(c for c in report['calculations'] if c['name']=='Revenue change from prior month')
    assert growth['value']=='20.00'
    assert '\n'.join(model.input['source_blocks'].values())==TEXT


@pytest.mark.parametrize('patch',[
    {'quote':'GMV: 8 lakh','number_text':'8 lakh'},
])
def test_gmv_cannot_be_assigned_to_revenue(patch):
    raw=model_result();raw['months']=raw['months'][:1]
    raw['months'][0]['observations'][0].update(patch)
    result=extract_metric_update(TEXT,'Founder monthly report','Hotel Example',ExtractionModel(raw))
    assert not result['updates']
    assert result['issues']


@pytest.mark.parametrize('quote,value',[('Projected revenue: 100','100'),('Revenue: 20%','20'),('Revenue: approximately 100','100'),('Annual revenue: 100','100')])
def test_forecasts_estimates_percentages_and_annual_figures_are_exceptions(quote,value):
    raw=model_result();raw['months']=raw['months'][:1];raw['months'][0]['observations']=[dict(field='revenue',quote=quote,number_text=value)]
    result=extract_metric_update(TEXT+'\nJanuary 2025\n'+quote,'Founder monthly report','Hotel Example',ExtractionModel(raw))
    assert not result['updates']


def test_ambiguous_currency_and_duplicate_months_are_not_saved():
    for raw in [model_result(),model_result()]:
        if len(raw['months'])==2:
            raw['months']=raw['months'][:1]
        raw['months'][0]['currency_quote']='$'
        assert not extract_metric_update(TEXT+' $','Founder monthly report','Hotel Example',ExtractionModel(raw))['updates']
    raw=model_result();raw['months']=[raw['months'][0],raw['months'][0]]
    assert not extract_metric_update(TEXT,'Founder monthly report','Hotel Example',ExtractionModel(raw))['updates']


def test_import_job_scoping_revision_retained_sources_and_automatic_brief(tmp_path,monkeypatch):
    from store import Store
    from tests.test_operating_workflow import company
    from tests.test_company_brief import BriefModel
    from agents.operating_workflow import reconcile_workspace
    from agents.company_brief import brief_current
    import api.routers.operations as api
    class CombinedModel(BriefModel):
        def generate(self,instruction,payload,schema):
            if schema.__name__=='SelectedUpdate':return ExtractionModel().generate(instruction,payload,schema)
            return super().generate(instruction,payload,schema)
    monkeypatch.setattr(api,'LocalModel',CombinedModel)
    with Store(tmp_path/'db') as store:
        lead=company(store);w=reconcile_workspace(store,lead)
        body=api.MetricImportRequest(expected_revision=w.revision,source_name='Founder monthly report',text=TEXT)
        with pytest.raises(HTTPException) as wrong:api.import_metrics(w.id,body,BackgroundTasks(),store,'other')
        assert wrong.value.status_code==404
        tasks=BackgroundTasks();queued=api.import_metrics(w.id,body,tasks,store,'one')
        assert queued.metric_imports[-1]['text']==TEXT
        assert queued.automation.status=='queued'
        with pytest.raises(HTTPException) as stale:api.import_metrics(w.id,body,BackgroundTasks(),store,'one')
        assert stale.value.status_code==409
        task=tasks.tasks[0];task.func(*task.args,**task.kwargs)
        done=store.get_workspace('one',lead_id=lead.id)
        assert done.automation.status=='completed',done.automation.error
        assert brief_current(done)
        assert len(done.metric_updates)==2
        assert done.metric_imports[-1]['status']=='applied'
        assert done.metric_updates[0]['field_sources']['revenue']['quote']=='Revenue: 1 lakh'
        assert not done.capabilities['external_sending']
        assert 'model_generated'==done.company_brief['pitch']['generation']['kind']
        assert len(done.company_brief['research']['generation']['evidence_ids'])==3


def test_no_accepted_actuals_leaves_previous_brief_and_no_fake_metrics(tmp_path,monkeypatch):
    from store import Store
    from tests.test_operating_workflow import company
    from agents.operating_workflow import reconcile_workspace
    import api.routers.operations as api
    monkeypatch.setattr(api,'LocalModel',lambda:ExtractionModel(dict(months=[],issues=['Month and currency are missing.'])))
    with Store(tmp_path/'db') as store:
        lead=company(store);w=reconcile_workspace(store,lead)
        tasks=BackgroundTasks();api.import_metrics(w.id,api.MetricImportRequest(expected_revision=w.revision,source_name='Founder monthly report',text='The founder says growth is strong without dated metrics.'),tasks,store,'one')
        task=tasks.tasks[0];task.func(*task.args,**task.kwargs)
        done=store.get_workspace('one',lead_id=lead.id)
        assert done.automation.status=='failed'
        assert done.metric_updates==[]
        assert done.metric_imports[-1]['status']=='needs_input'
        assert 'Month and currency' in done.metric_imports[-1]['issues'][0]


def test_explicit_month_name_normalizes_without_inference():
    raw=model_result();raw['months'][0]['month']='January 2025'
    assert extract_metric_update(TEXT,'Founder monthly report','Hotel Example',ExtractionModel(raw))['updates'][0]['month']=='2025-01'


def test_cannot_bind_another_months_value_or_strip_forecast_qualifier():
    raw=model_result();raw['months']=raw['months'][:1]
    raw['months'][0]['observations']=[dict(field='revenue',quote='Revenue: 1.2 lakh',number_text='1.2 lakh')]
    assert not extract_metric_update(TEXT,'Founder monthly report','Hotel Example',ExtractionModel(raw))['updates']
    raw['months'][0]['observations']=[dict(field='revenue',quote='Revenue: 100',number_text='100')]
    assert not extract_metric_update('Currency: INR.\nJanuary 2025\nProjected Revenue: 100','Founder monthly report','Hotel Example',ExtractionModel(raw))['updates']


def test_partial_update_retains_prior_figures_and_each_field_source(tmp_path):
    from store import Store
    from tests.test_operating_workflow import company
    from agents.operating_workflow import reconcile_workspace
    from workflow_schemas import AutomationRun
    from api.routers.operations import _apply_metric_import
    raw=model_result();raw['months']=raw['months'][:1];raw['months'][0]['observations']=raw['months'][0]['observations'][:1]
    with Store(tmp_path/'db') as store:
        lead=company(store);w=reconcile_workspace(store,lead)
        w.metric_updates=[dict(id='old',month='2025-01',currency='INR',source_note='January finance report',cash='900',revenue='500')]
        w.metric_imports=[dict(id='new',source_name='January corrected sales',text=TEXT,status='queued')]
        w.automation=AutomationRun(model='fixture',worker_id='fixture')
        store.save_workspace(w,expected_revision=w.revision)
        _apply_metric_import(store,w,'new',ExtractionModel(raw))
        done=store.get_workspace('one',workspace_id=w.id)
        assert len(done.metric_updates)==2
        assert done.metric_updates[-1]['cash']=='900'
        assert done.metric_updates[-1]['revenue']=='100000'
        assert done.metric_updates[-1]['field_sources']['cash']['record_id']=='old'
        assert done.metric_updates[-1]['field_sources']['revenue']['import_id']=='new'


def test_unknown_source_block_rejected_by_schema_and_retry():
    raw=model_result();raw['months'][0]['observations'][0]['quote']='invented revenue: 999'
    with pytest.raises(ValueError):
        extract_metric_update(TEXT,'Founder monthly report','Hotel Example',ExtractionModel(raw))
