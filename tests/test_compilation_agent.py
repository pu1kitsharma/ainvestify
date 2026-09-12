"""
Coverage for the Milestone 4 build/render split (agents/compilation_agent.py):
build_*_data produces the structured JSON a frontend will render; render_*_
markdown produces the same Markdown the CLI/archival file has always had.
The teaser allowlist gets the most scrutiny -- the plan's own stated
verification bar is confirming its output JSON contains no identity-bearing
keys, not just eyeballing it.
"""
from conftest import make_extraction_result

from agents.compilation_agent import (
    build_cim_data,
    build_teaser_data,
    generate_proforma_projection,
    render_cim_markdown,
    render_proforma_markdown,
    render_teaser_markdown,
)
from schemas import CapTableRow, ChartArtifact, FieldStatus, FundingRound, ResearchFinding

TENANT, DEAL = "tenant_test", "deal_test"


def _fully_approved_result(**overrides):
    result = make_extraction_result(**overrides)
    for name in ("arr", "arr_prior_year", "burn_monthly", "cash_on_hand", "runway_months", "headcount"):
        getattr(result, name).status = FieldStatus.APPROVED
    for name in ("mrr", "growth_rate_yoy"):
        getattr(result, name).status = FieldStatus.NOT_FOUND
    return result


# --- Teaser allowlist --------------------------------------------------

def test_teaser_data_contains_no_identity_bearing_keys():
    result = _fully_approved_result(
        cap_table=[CapTableRow(holder="Founder", pct=80)],
        funding_history=[FundingRound(round_name="Seed", amount=1_500_000, source_block_id="blk_3")],
    )
    charts = [
        ChartArtifact(tenant_id=TENANT, deal_id=DEAL, chart_type="arr_growth_bar", storage_uri="arr.png"),
        ChartArtifact(tenant_id=TENANT, deal_id=DEAL, chart_type="burn_vs_cash", storage_uri="burn.png"),
    ]
    data = build_teaser_data(result, charts, "Acme Robotics", "A robotics platform.", version_number=1)

    banned_keys = {"deal_id", "deal_name", "tenant_id", "cap_table", "funding_history", "external_signals"}
    assert banned_keys.isdisjoint(data.keys())
    assert set(data.keys()) == {"generated_at", "version_number", "business_description", "financials", "charts"}
    # Only the allowlisted 5 fields, nothing else.
    assert set(data["financials"].keys()) == {"arr", "growth_rate_yoy", "burn_monthly", "runway_months", "headcount"}
    # Non-arr-growth charts must never make it through.
    assert len(data["charts"]) == 1
    assert data["charts"][0]["chart_type"] == "arr_growth_bar"
    # No source citations on teaser financials -- the CIM has these, the teaser doesn't.
    for field in data["financials"].values():
        assert field["source_block_id"] is None
        assert field["source_page"] is None


def test_teaser_data_scrubs_company_name_from_business_description():
    result = _fully_approved_result()
    data = build_teaser_data(
        result, [], "Acme Robotics",
        "Acme Robotics builds warehouse manipulator arms.",
        version_number=1,
    )
    assert "Acme Robotics" not in data["business_description"]
    assert "[Company]" in data["business_description"]


def test_teaser_markdown_never_mentions_company_name():
    result = _fully_approved_result()
    data = build_teaser_data(result, [], "Acme Robotics", "A robotics platform for warehouses.", 1)
    rendered = render_teaser_markdown(data)
    assert "Acme Robotics" not in rendered


# --- CIM build/render ----------------------------------------------------

def test_cim_data_includes_only_approved_external_signals():
    result = _fully_approved_result()
    findings = [
        ResearchFinding(tenant_id=TENANT, deal_id=DEAL, topic="oss", content="approved one",
                         source_type="github", status=FieldStatus.APPROVED),
        ResearchFinding(tenant_id=TENANT, deal_id=DEAL, topic="oss", content="rejected one",
                         source_type="github", status=FieldStatus.REJECTED),
    ]
    data = build_cim_data(result, [], research_findings=findings, version_number=1, include_narrative=False)
    assert len(data["external_signals"]) == 1
    assert data["external_signals"][0]["content"] == "approved one"


def test_cim_data_cap_table_not_available_when_rejected():
    result = _fully_approved_result(cap_table=[CapTableRow(holder="Founder", pct=100)])
    result.cap_table_status = FieldStatus.REJECTED
    data = build_cim_data(result, [], version_number=1, include_narrative=False)
    assert data["cap_table"]["available"] is False
    assert data["cap_table"]["rows"] == []


def test_cim_markdown_renders_not_disclosed_for_not_found_field():
    result = _fully_approved_result()  # mrr is NOT_FOUND
    data = build_cim_data(result, [], version_number=1, include_narrative=False)
    rendered = render_cim_markdown(data)
    assert "**MRR:** Not disclosed" in rendered


def test_cim_markdown_includes_source_citation():
    result = _fully_approved_result()
    data = build_cim_data(result, [], version_number=1, include_narrative=False)
    rendered = render_cim_markdown(data)
    assert "[source: blk_1, page 1]" in rendered


# --- Pro-forma -------------------------------------------------------------

def test_proforma_projection_carries_is_projected_marker():
    result = _fully_approved_result()
    projection = generate_proforma_projection(result, years=2)
    assert projection["is_projected"] is True


def test_proforma_markdown_labels_itself_projected_not_extracted():
    result = _fully_approved_result()
    projection = generate_proforma_projection(result, years=1)
    rendered = render_proforma_markdown(result, projection, version_number=1)
    assert "PROJECTED, NOT EXTRACTED" in rendered
