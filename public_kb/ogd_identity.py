"""Offline, rights-gated identity observations from an operator-supplied OGD export.

This module does no downloading, scheduling, room access, fuzzy matching, or
investment eligibility inference. An operator must separately inspect the exact
Company Master Data resource and approve its dataset-level rights before import.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence
from urllib.parse import urlparse


LICENSE_NAME = "Government Open Data License - India"
LICENSE_URL = "https://ap.data.gov.in/godl"
CATALOG_URL = "https://www.data.gov.in/catalog/company-master-data"
_CIN = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FIELD_ALIASES = {
    "cin": "cin",
    "entity_key": "entity_key",
    "company_name": "company_name",
    "company_status": "company_status",
    "date_of_incorporation": "date_of_incorporation",
}


def _iso(value: object, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _ogd_url(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an official OGD URL")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.hostname not in {"data.gov.in", "www.data.gov.in", "api.data.gov.in"}
            or parsed.path in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError(f"{field} must be an official OGD URL")
    return value


@dataclass(frozen=True)
class ExportProvenance:
    provider: str
    catalog_url: str
    resource_url: str
    resource_id: str
    version: str
    published_on: date
    retrieved_on: date
    license_name: str
    license_url: str
    attribution: str
    reviewed_by: str
    reviewed_on: date
    rights_expires_on: date
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object], *, today: date) -> "ExportProvenance":
        required = (
            "provider", "catalog_url", "resource_url", "resource_id", "version",
            "published_on", "retrieved_on", "license_name", "license_url",
            "attribution", "reviewed_by", "reviewed_on", "rights_expires_on",
            "sha256", "dataset_license_confirmed", "rights_approved_for_kb",
        )
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"missing export provenance: {', '.join(missing)}")
        if value["dataset_license_confirmed"] is not True or value["rights_approved_for_kb"] is not True:
            raise PermissionError("exact dataset license and KB rights must be reviewed")
        if value["provider"] != "Ministry of Corporate Affairs":
            raise ValueError("unexpected OGD data provider")
        if value["catalog_url"] != CATALOG_URL:
            raise ValueError("unexpected Company Master Data catalog")
        _ogd_url(value["resource_url"], "resource_url")
        if value["resource_url"] == CATALOG_URL:
            raise ValueError("resource URL must identify the reviewed export resource")
        if value["license_name"] != LICENSE_NAME or value["license_url"] != LICENSE_URL:
            raise PermissionError("individual dataset license is unconfirmed or changed")
        for field in ("resource_id", "version", "attribution", "reviewed_by"):
            if not isinstance(value[field], str) or not value[field].strip():
                raise ValueError(f"{field} is required")
        if not _VERSION.fullmatch(value["resource_id"]) or not _VERSION.fullmatch(value["version"]):
            raise ValueError("resource/version identifier is invalid")
        digest = value["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("sha256 must be a lowercase hex digest")
        published = _iso(value["published_on"], "published_on")
        retrieved = _iso(value["retrieved_on"], "retrieved_on")
        reviewed = _iso(value["reviewed_on"], "reviewed_on")
        expiry = _iso(value["rights_expires_on"], "rights_expires_on")
        if published > retrieved or retrieved > today or reviewed > today or expiry < today:
            raise PermissionError("dataset publication, retrieval or rights review is not current")
        if reviewed < retrieved:
            raise ValueError("rights review must inspect the retrieved export")
        attribution = value["attribution"]
        if not all(part in attribution for part in (value["provider"], value["version"],
                                                    value["catalog_url"], LICENSE_NAME)):
            raise ValueError("attribution must identify provider, version, catalog and license")
        return cls(
            provider=value["provider"], catalog_url=value["catalog_url"],
            resource_url=value["resource_url"], resource_id=value["resource_id"],
            version=value["version"], published_on=published, retrieved_on=retrieved,
            license_name=value["license_name"], license_url=value["license_url"],
            attribution=attribution, reviewed_by=value["reviewed_by"],
            reviewed_on=reviewed, rights_expires_on=expiry, sha256=digest,
        )

    @property
    def source_version_id(self) -> str:
        return f"ogd-mca:{self.resource_id}:{self.version}:{self.sha256}"


@dataclass(frozen=True)
class IdentityObservation:
    entity_key: str
    cin: str
    company_name: str
    company_status: str
    incorporation_date: date | None
    reported_as_of: date
    source_version_id: str
    source_row: int
    source_url: str
    attribution: str


@dataclass(frozen=True)
class IdentityExport:
    provenance: ExportProvenance
    observations: tuple[IdentityObservation, ...]


@dataclass(frozen=True)
class IdentityProjection:
    entity_key: str
    cin: str
    company_name: str | None
    company_status: str | None
    incorporation_date: date | None
    latest_reported_as_of: date
    observations: tuple[IdentityObservation, ...]
    conflicts: tuple[str, ...]


def _header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def import_company_master_csv(
    content: bytes, metadata: Mapping[str, object], *, today: date,
    max_bytes: int = 25_000_000, max_rows: int = 200_000,
) -> IdentityExport:
    """Validate an exact export and retain only legal-entity identity/status fields.

    This bounded adapter does not write to the shared KB. Its output can be
    reviewed before an operator enables a separate ingest path.
    """
    if not isinstance(content, bytes) or len(content) > max_bytes:
        raise ValueError("export exceeds the configured byte bound")
    provenance = ExportProvenance.from_mapping(metadata, today=today)
    if hashlib.sha256(content).hexdigest() != provenance.sha256:
        raise ValueError("export bytes do not match the reviewed version digest")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("export must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
    if not reader.fieldnames:
        raise ValueError("export has no CSV header")
    normalized = [_header(name) for name in reader.fieldnames]
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate normalized CSV columns")
    required = {"cin", "company_name", "company_status"}
    if not required.issubset(normalized):
        raise ValueError("export lacks required MCA identity/status columns")
    mapping = {original: _FIELD_ALIASES.get(canonical) for original, canonical in zip(reader.fieldnames, normalized)}
    output: list[IdentityObservation] = []
    seen: dict[str, IdentityObservation] = {}
    try:
        for row_number, row in enumerate(reader, start=2):
            if row_number - 1 > max_rows:
                raise ValueError("export exceeds the configured row bound")
            if None in row:
                raise ValueError(f"row {row_number} has extra CSV fields")
            selected = {target: (row[source] or "").strip() for source, target in mapping.items() if target}
            cin = selected["cin"].upper()
            if not _CIN.fullmatch(cin):
                raise ValueError(f"row {row_number} has an invalid CIN")
            supplied_key = selected.get("entity_key")
            if supplied_key and supplied_key != f"IN:MCA:CIN:{cin}":
                raise ValueError(f"row {row_number} entity key conflicts with CIN")
            name, status = selected["company_name"], selected["company_status"]
            if not name or not status or len(name) > 300 or len(status) > 120:
                raise ValueError(f"row {row_number} has missing or oversized identity/status")
            incorporated = selected.get("date_of_incorporation", "")
            incorporation_date = _iso(incorporated, "date_of_incorporation") if incorporated else None
            if incorporation_date and incorporation_date > provenance.published_on:
                raise ValueError(f"row {row_number} incorporation date follows publication")
            observation = IdentityObservation(
                entity_key=f"IN:MCA:CIN:{cin}", cin=cin, company_name=name,
                company_status=status, incorporation_date=incorporation_date,
                reported_as_of=provenance.published_on,
                source_version_id=provenance.source_version_id, source_row=row_number,
                source_url=provenance.resource_url, attribution=provenance.attribution,
            )
            previous = seen.get(cin)
            if previous:
                if (previous.company_name, previous.company_status, previous.incorporation_date) != (
                    name, status, incorporation_date
                ):
                    raise ValueError(f"conflicting same-version CIN rows: {cin}")
                continue
            seen[cin] = observation
            output.append(observation)
    except csv.Error as exc:
        raise ValueError("malformed CSV export") from exc
    if not output:
        raise ValueError("export contains no company identity rows")
    return IdentityExport(provenance, tuple(output))


def reconcile_identity(cin: str, exports: Sequence[IdentityExport]) -> IdentityProjection:
    """Keep dated reports; make latest disputed fields explicitly unresolved."""
    if not _CIN.fullmatch(cin):
        raise ValueError("CIN must be canonical uppercase")
    versions: dict[tuple[str, str], str] = {}
    observations: list[IdentityObservation] = []
    for export in exports:
        key = (export.provenance.resource_id, export.provenance.version)
        digest = versions.setdefault(key, export.provenance.sha256)
        if digest != export.provenance.sha256:
            raise ValueError("same resource/version has differing bytes")
        observations.extend(row for row in export.observations if row.cin == cin)
    if not observations:
        raise ValueError("CIN absent from supplied exports")
    # Identical import replays are harmless; all distinct source versions remain.
    observations = list({(row.source_version_id, row.source_row): row for row in observations}.values())
    observations.sort(key=lambda row: (row.reported_as_of, row.source_version_id, row.source_row))
    latest = observations[-1].reported_as_of
    current = [row for row in observations if row.reported_as_of == latest]
    conflicts: list[str] = []

    def pick(field: str):
        values = {getattr(row, field) for row in current if getattr(row, field) is not None}
        if len(values) > 1:
            conflicts.append(field)
            return None
        return next(iter(values), None)

    return IdentityProjection(
        entity_key=f"IN:MCA:CIN:{cin}", cin=cin,
        company_name=pick("company_name"), company_status=pick("company_status"),
        incorporation_date=pick("incorporation_date"), latest_reported_as_of=latest,
        observations=tuple(observations), conflicts=tuple(conflicts),
    )
