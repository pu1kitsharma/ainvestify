"""Historical reads remain, but legacy write routes cannot generate prose."""
import pytest
from fastapi import HTTPException

from api.models import RunResearchRequest
from api.routers import compilation, research


class NoStoreUse:
    def __getattr__(self, name):
        raise AssertionError(f"Legacy store path ran: {name}")


@pytest.mark.parametrize("invoke", [
    lambda store: research.run_research("deal", RunResearchRequest(company_name="Example"), store, "tenant"),
    lambda store: compilation.compile_cim_endpoint("deal", store, "tenant"),
    lambda store: compilation.compile_teaser_draft_endpoint(
        "deal", compilation.TeaserDraftRequest(business_description="Example"), store, "tenant"),
    lambda store: compilation.confirm_teaser_endpoint(
        "deal", "memo", compilation.TeaserConfirmRequest(confirmed=True), store, "tenant", "reviewer"),
    lambda store: compilation.compile_proforma_endpoint(
        "deal", compilation.ProformaRequest(), store, "tenant", "reviewer"),
])
def test_legacy_generation_routes_fail_before_connectors_or_templates(invoke):
    with pytest.raises(HTTPException) as error:
        invoke(NoStoreUse())
    assert error.value.status_code == 410
    assert "deal room" in error.value.detail.lower()
