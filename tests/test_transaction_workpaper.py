from types import SimpleNamespace
import pytest
from schemas import Document, DocBlock, ExtractionResult, ExtractedValue
from agents.transaction_workpaper import preparation_workpaper


def fixture():
    lead = SimpleNamespace(tenant_id='one', promoted_deal_id='deal')
    doc = Document(id='doc', tenant_id='one', deal_id='deal', filename='records.pdf', type='pdf', storage_uri='records.pdf', blocks=[DocBlock(id='b', document_id='doc', page=1, block_type='text', coordinates={}, content='Financial records')])
    extraction = ExtractionResult(tenant_id='one', deal_id='deal', document_id='doc')
    for key, value in [('arr', 150), ('arr_prior_year', 100), ('cash_on_hand', 120), ('burn_monthly', 10)]:
        setattr(extraction, key, ExtractedValue(value=value, unit='INR', status='approved', source_block_id='b', source_page=1))
    return lead, doc, extraction


def test_calculations_keep_source_and_explicit_limits():
    lead, doc, extraction = fixture()
    result = preparation_workpaper(lead, [doc], extraction, [])
    assert [c['value'] for c in result['calculations']] == ['12.00', '50.00']
    assert all(c['limitation'] and c['inputs'] for c in result['calculations'])
    assert all(f['source_block_id'] == 'b' for f in result['financials'])
    assert result['requests'][1]['status'] == 'partial'
    assert result['next_deliverable'] == 'Transaction objectives and engagement scope'


@pytest.mark.parametrize('field,value', [('status','proposed'), ('status','rejected'), ('source_page',2), ('source_block_id','missing'), ('value',True), ('value','NaN'), ('value','garbage')])
def test_unreviewed_or_untraceable_input_cannot_support_calculation(field,value):
    lead, doc, extraction = fixture()
    setattr(extraction.cash_on_hand, field, value)
    result = preparation_workpaper(lead, [doc], extraction, [])
    assert not any(c['unit']=='months' for c in result['calculations'])
    assert next(f for f in result['financials'] if f['key']=='cash_on_hand')['value'] is None


@pytest.mark.parametrize('target,field,value', [('document','tenant_id','other'), ('document','deal_id','other'), ('extraction','tenant_id','other'), ('extraction','deal_id','other'), ('extraction','document_id','other')])
def test_scope_mismatch_excludes_private_figures(target,field,value):
    lead, doc, extraction = fixture()
    setattr(doc if target=='document' else extraction,field,value)
    result = preparation_workpaper(lead, [doc], extraction, [])
    assert result['calculations'] == []
    assert all(f['value'] is None for f in result['financials'])


@pytest.mark.parametrize('burn,unit', [(0,'INR'),(-1,'INR'),(10,'USD'),(10,'')])
def test_cash_coverage_requires_positive_burn_and_matching_units(burn,unit):
    lead, doc, extraction = fixture()
    extraction.burn_monthly.value = burn
    extraction.burn_monthly.unit = unit
    result = preparation_workpaper(lead, [doc], extraction, [])
    assert not any(c['unit']=='months' for c in result['calculations'])


def test_data_request_is_available_without_generated_prose_and_tenant_scoped(tmp_path):
    from store import Store
    from tests.test_operating_workflow import company
    from agents.operating_workflow import reconcile_workspace
    from api.routers.operations import data_request
    from fastapi import HTTPException
    with Store(tmp_path/'db') as store:
        lead = company(store)
        workspace = reconcile_workspace(store,lead)
        response = data_request(workspace.id,store,'one')
        assert 'Hotel Example' in response.body.decode()
        assert 'Completion criteria:' in response.body.decode()
        assert 'Not sent' in response.body.decode()
        with pytest.raises(HTTPException) as err:
            data_request(workspace.id,store,'other')
        assert err.value.status_code == 404
