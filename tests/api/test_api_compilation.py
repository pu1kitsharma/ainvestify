"""Retired generators fail closed; authenticated historical documents remain readable."""
from pathlib import Path

import pytest

from agents.core.planner_agent import start_deal
from schemas import CompanyProfile, MemoVersion, SourcedLead
from store import Store
from tests.api.test_authentication import secured, sign_in


@pytest.mark.parametrize('suffix,payload', [
    ('compile/cim', None),
    ('compile/teaser/draft', {'business_description': 'Synthetic description'}),
    ('compile/teaser/unknown/confirm', {'confirmed': True}),
    ('compile/proforma', {'growth_rate_override': 42.0}),
])
def test_retired_compilation_is_410_without_artifact_or_memo_writes(secured, suffix, payload):
    client, db, users = secured
    sign_in(client, users[0])
    tenant = users[0][1]
    with Store(db) as store:
        deal = start_deal(store, tenant, 'Synthetic company')
        before = store.get_deal(tenant, deal.id).model_dump(mode='json')
    # Check the actual historical artifact location without creating/deleting it.
    output = Path(__file__).resolve().parents[2] / 'memo_output' / deal.id
    assert not output.exists()
    response = client.post(f'/api/deals/{deal.id}/{suffix}', json=payload)
    assert response.status_code == 410
    assert 'retired' in response.json()['detail']
    assert not output.exists()
    with Store(db) as store:
        assert store.get_memo_versions(tenant, deal.id) == []
        assert store.get_deal(tenant, deal.id).model_dump(mode='json') == before


def test_authenticated_documents_filter_latest_and_tenant_isolation(secured):
    client, db, users = secured
    tenant = users[0][1]
    with Store(db) as store:
        deal = start_deal(store, tenant, 'Synthetic archive')
        for kind, version in [('cim', 1), ('teaser', 1), ('cim', 2)]:
            store.save_memo_version(MemoVersion(tenant_id=tenant, deal_id=deal.id,
                version_number=version, content_uri='unused.md', document_type=kind))
    url = f'/api/deals/{deal.id}/documents'
    assert client.get(url).status_code == 401
    sign_in(client, users[0])
    all_docs = client.get(url)
    assert all_docs.status_code == 200 and len(all_docs.json()) == 3
    filtered = client.get(url, params={'document_type': 'cim'})
    assert filtered.status_code == 200 and len(filtered.json()) == 2
    assert all(row['document_type'] == 'cim' for row in filtered.json())
    latest = client.get(url + '/latest', params={'document_type': 'cim'})
    assert latest.status_code == 200 and latest.json()['version_number'] == 2
    assert client.get(url + '/latest', params={'document_type': 'proforma'}).status_code == 404
    sign_in(client, users[1])
    assert client.get(url).status_code == 404
    assert client.get(url + '/latest', params={'document_type': 'cim'}).status_code == 404


def test_authored_workspace_documents_cannot_inherit_legacy_approval(secured):
    from agents.analysis.operating_workflow import reconcile_workspace
    client, db, users = secured
    tenant = users[0][1]
    sign_in(client, users[0])
    with Store(db) as store:
        deal = start_deal(store, tenant, 'Synthetic company')
        profile = CompanyProfile(tenant_id=tenant, name=deal.name, website='https://company.example/',
                                 provenance={'pipeline': 'model_authored_v1'})
        lead = SourcedLead(tenant_id=tenant, company_name=deal.name,
                          company_profile=profile, promoted_deal_id=deal.id)
        store.save_lead(lead)
        workspace = reconcile_workspace(store, lead)
        assert workspace.work_items == []
        memo = MemoVersion(tenant_id=tenant, deal_id=deal.id, version_number=1,
            content_uri='unused.md', document_type='teaser', approved_by='historical reviewer',
            approval_basis_hash=workspace.basis_hash)
        store.save_memo_version(memo)
    url = f'/api/deals/{deal.id}/documents'
    for response in (client.get(url), client.get(url + '/latest?document_type=teaser')):
        assert response.status_code == 200
        body = response.json()
        assert (body[0] if isinstance(body, list) else body)['approved_by'] is None
    response = client.post(f'/api/deals/{deal.id}/compile/teaser/{memo.id}/confirm', json={'confirmed': True})
    assert response.status_code == 410
    with Store(db) as store:
        assert store.get_memo_version(tenant, memo.id).approved_by == 'historical reviewer'


def test_rerun_analytics_over_authenticated_http(secured, tmp_path, monkeypatch):
    """The remaining deterministic analytics route still persists actual charts."""
    from tests.conftest import make_extraction_result
    from schemas import FieldStatus
    client, db, users = secured
    tenant = users[0][1]
    sign_in(client, users[0])
    monkeypatch.chdir(tmp_path)  # Synthetic chart files never enter repository storage.
    with Store(db) as store:
        deal = start_deal(store, tenant, 'Synthetic analytics')
        result = make_extraction_result(tenant_id=tenant, deal_id=deal.id)
        result.arr.status = result.arr_prior_year.status = FieldStatus.APPROVED
        store.save_extraction_result(result)
    response = client.post(f'/api/deals/{deal.id}/analytics/rerun')
    assert response.status_code == 200
    assert response.json()
    for chart in response.json():
        assert Path(chart['storage_uri']).is_file()
    with Store(db) as store:
        assert len(store.get_charts(tenant, deal.id)) == len(response.json())
