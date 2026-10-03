"""Synthetic-only checks for a disabled, operator-supplied OGD export adapter."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from public_kb.ogd_identity import (
    CATALOG_URL, LICENSE_NAME, LICENSE_URL,
    import_company_master_csv, reconcile_identity,
)


CIN = "U12345KA2022PTC123456"
TODAY = date(2026, 10, 3)


def _csv(*rows: str) -> bytes:
    return ("CIN,Company Name,Company Status,Date of Incorporation,Entity Key,Director Name\n"
            + "\n".join(rows) + "\n").encode()


def _metadata(data: bytes, *, version: str = "2026-09", published: str = "2026-09-30") -> dict:
    return {
        "provider": "Ministry of Corporate Affairs", "catalog_url": CATALOG_URL,
        "resource_url": "https://www.data.gov.in/resource/synthetic-company-master",
        "resource_id": "synthetic-resource", "version": version,
        "published_on": published, "retrieved_on": "2026-10-01",
        "license_name": LICENSE_NAME, "license_url": LICENSE_URL,
        "attribution": f"Ministry of Corporate Affairs, {version}, Company Master Data, "
                       f"{CATALOG_URL}. Published under {LICENSE_NAME}.",
        "reviewed_by": "operator-test", "reviewed_on": "2026-10-02",
        "rights_expires_on": "2026-12-31",
        "sha256": hashlib.sha256(data).hexdigest(),
        "dataset_license_confirmed": True, "rights_approved_for_kb": True,
    }


def test_import_retains_only_source_reported_identity_and_dated_lineage():
    data = _csv(f"{CIN},Synthetic Labs Private Limited,Active,2022-01-02,IN:MCA:CIN:{CIN},Private Person")
    export = import_company_master_csv(data, _metadata(data), today=TODAY)
    (row,) = export.observations
    assert row.entity_key == f"IN:MCA:CIN:{CIN}"
    assert row.company_status == "Active"
    assert row.incorporation_date == date(2022, 1, 2)
    assert row.reported_as_of == date(2026, 9, 30)
    assert row.source_row == 2
    assert export.provenance.sha256 in row.source_version_id
    assert "Private Person" not in repr(export)
    assert not hasattr(row, "funding_stage")


@pytest.mark.parametrize("change", [
    {"dataset_license_confirmed": False}, {"rights_approved_for_kb": False},
    {"license_name": "unknown"}, {"catalog_url": "https://example.com"},
    {"resource_url": "https://evil.example/resource"},
    {"rights_expires_on": "2026-10-02"},
    {"reviewed_on": "2026-09-30"},
    {"provider": "Unknown Publisher"},
])
def test_metadata_fails_closed(change):
    data = _csv(f"{CIN},Synthetic Labs,Active,,," )
    metadata = _metadata(data)
    metadata.update(change)
    with pytest.raises((ValueError, PermissionError)):
        import_company_master_csv(data, metadata, today=TODAY)


def test_exact_bytes_and_entity_key_must_bind():
    data = _csv(f"{CIN},Synthetic Labs,Active,,IN:MCA:CIN:{CIN},")
    metadata = _metadata(data)
    with pytest.raises(ValueError, match="digest"):
        import_company_master_csv(data + b" ", metadata, today=TODAY)
    wrong = _csv(f"{CIN},Synthetic Labs,Active,,IN:MCA:CIN:OTHER,")
    with pytest.raises(ValueError, match="entity key"):
        import_company_master_csv(wrong, _metadata(wrong), today=TODAY)


def test_invalid_cin_and_ambiguous_same_version_rejected():
    invalid = _csv("NOT-CIN,Synthetic Labs,Active,,,")
    with pytest.raises(ValueError, match="invalid CIN"):
        import_company_master_csv(invalid, _metadata(invalid), today=TODAY)
    conflicting = _csv(
        f"{CIN},Synthetic Labs,Active,,IN:MCA:CIN:{CIN},",
        f"{CIN},Synthetic Labs,Strike Off,,IN:MCA:CIN:{CIN},",
    )
    with pytest.raises(ValueError, match="conflicting same-version"):
        import_company_master_csv(conflicting, _metadata(conflicting), today=TODAY)


def test_reconciliation_keeps_history_and_newer_reported_status():
    old = _csv(f"{CIN},Synthetic Labs,Active,,,")
    new = _csv(f"{CIN},Synthetic Labs,Strike Off,,,")
    earlier = import_company_master_csv(old, _metadata(old, version="2026-08", published="2026-08-31"), today=TODAY)
    later = import_company_master_csv(new, _metadata(new), today=TODAY)
    projection = reconcile_identity(CIN, [earlier, later, later])
    assert projection.company_status == "Strike Off"
    assert projection.latest_reported_as_of == date(2026, 9, 30)
    assert [row.company_status for row in projection.observations] == ["Active", "Strike Off"]
    assert projection.conflicts == ()


def test_same_date_conflict_is_unresolved_and_both_sources_retained():
    first = _csv(f"{CIN},Synthetic Labs,Active,,,")
    second = _csv(f"{CIN},Synthetic Labs,Strike Off,,,")
    a = import_company_master_csv(first, _metadata(first, version="rev-a"), today=TODAY)
    b = import_company_master_csv(second, _metadata(second, version="rev-b"), today=TODAY)
    projection = reconcile_identity(CIN, [a, b])
    assert projection.company_status is None
    assert projection.company_name == "Synthetic Labs"
    assert projection.conflicts == ("company_status",)
    assert len(projection.observations) == 2


def test_same_version_digest_conflict_is_rejected():
    first = _csv(f"{CIN},Synthetic Labs,Active,,,")
    second = _csv(f"{CIN},Synthetic Labs,Strike Off,,,")
    a = import_company_master_csv(first, _metadata(first), today=TODAY)
    b = import_company_master_csv(second, _metadata(second), today=TODAY)
    with pytest.raises(ValueError, match="same resource/version"):
        reconcile_identity(CIN, [a, b])


def test_bounded_csv_rejects_oversized_and_extra_fields():
    data = _csv(f"{CIN},Synthetic Labs,Active,,,")
    with pytest.raises(ValueError, match="byte bound"):
        import_company_master_csv(data, _metadata(data), today=TODAY, max_bytes=10)
    with pytest.raises(ValueError, match="row bound"):
        import_company_master_csv(data, _metadata(data), today=TODAY, max_rows=0)
    extra = _csv(f"{CIN},Synthetic Labs,Active,,,,extra")
    with pytest.raises(ValueError, match="extra CSV fields"):
        import_company_master_csv(extra, _metadata(extra), today=TODAY)
