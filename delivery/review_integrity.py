"""Server-side source receipts and scoped human qualifications for release.

These checks prove retained bytes and authority, never financial or legal truth.
No HTTP request, model result or workspace field can provision these records.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from urllib.parse import urlsplit

from delivery.storage import MAX_FILE_BYTES


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _json_hash(value):
    return _hash(json.dumps(value, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":")).encode())


@dataclass(frozen=True)
class RetainedOfficialSource:
    reference_id: str
    source_url: str
    source_sha256: str
    size_bytes: int
    receipt_sha256: str


@dataclass(frozen=True)
class BoundEvidenceInventory:
    tenant_id: str
    workspace_id: str
    evidence_revision: str
    # Values bind the actual original/version plus the exact retained record.
    evidence: dict[str, str]


def _read_beneath(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(
            part in {"", ".", ".."} for part in parts):
        raise ValueError("Unsafe retained-source path")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
                raise ValueError("Unsupported retained-source inode")
            body = stream.read(MAX_FILE_BYTES + 1)
        if not body or len(body) > MAX_FILE_BYTES:
            raise ValueError("Unsupported retained-source size")
        return body
    finally:
        os.close(directory)


def retained_official_sources(register_path, project_root):
    """Rehash server-configured body AND retrieval receipt on every assessment.

    Missing or malformed references are not admitted. Retrieval is deliberately
    separate from qualified currentness, effective dates and applicability.
    """
    prefix = ("runtime_qualification", "regulatory_sources")
    project_root = Path(project_root)

    def read_record_path(value):
        parts = PurePosixPath(value).parts
        if parts[:2] != prefix or len(parts) < 3:
            raise ValueError("Source is outside the server regulatory archive")
        return _read_beneath(project_root, str(PurePosixPath(*parts)))

    try:
        register_relative = Path(register_path).relative_to(project_root)
        register = json.loads(_read_beneath(project_root, register_relative.as_posix()))
        if register.get("contract") != "official-regulatory-reference-v1":
            return {}
        sources = register["sources"]
        if not isinstance(sources, list):
            return {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    admitted, duplicate_urls = {}, set()
    for item in sources:
        try:
            url = item["official_url"]
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != item["host"]
                    or not parsed.hostname or parsed.username or parsed.password
                    or parsed.port not in (None, 443)
                    or item.get("fetch_status") != "source_bytes_retained"):
                continue
            body = read_record_path(item["source_bytes_path"])
            sha = _hash(body)
            if sha != item["source_sha256"] or len(body) != item["source_byte_length"]:
                continue
            receipt_hash = None
            for receipt_ref in item.get("retrieval_receipts", []):
                receipt_bytes = read_record_path(receipt_ref["receipt_path"])
                if _hash(receipt_bytes) != receipt_ref["receipt_sha256"]:
                    continue
                receipt = json.loads(receipt_bytes)
                resolved = urlsplit(receipt.get("resolved_url", ""))
                if (receipt.get("contract") == "official-source-byte-receipt-v1"
                        and receipt.get("fetch_status") == "source_bytes_retained"
                        and receipt.get("reference_id") == item["reference_id"]
                        and receipt.get("requested_url") == url
                        and resolved.scheme == "https" and resolved.hostname == parsed.hostname
                        and not resolved.username and not resolved.password
                        and resolved.port in (None, 443)
                        and receipt.get("response_body_path") == item["source_bytes_path"]
                        and receipt.get("source_sha256") == sha
                        and receipt.get("response_body_sha256") == sha
                        and receipt.get("byte_length") == len(body)
                        and receipt.get("http_status") == 200):
                    receipt_hash = _hash(receipt_bytes)
                    break
            if receipt_hash is None:
                continue
            if url in admitted:
                duplicate_urls.add(url)
                continue
            admitted[url] = RetainedOfficialSource(item["reference_id"], url, sha,
                                                   len(body), receipt_hash)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return {url: record for url, record in admitted.items() if url not in duplicate_urls}


def room_evidence_inventory(store, tenant, room, evidence_revision):
    """Resolve private records, never a caller-supplied evidence-ID dictionary.

    Documents must have readable original bytes. IDs are retained block IDs,
    private document/block URLs or private company-profile evidence IDs. Other
    aliases fail closed. Source-reported evidence is not independently verified.
    """
    from api.routers.rooms import revision_for
    from api.routers.deals import UPLOAD_ROOT
    from delivery.storage import scope_component

    try:
        if room.tenant_id != tenant or revision_for(store, room) != evidence_revision:
            return None
        lead = store.get_lead(tenant, room.lead_id)
        if lead is None or lead.tenant_id != tenant or lead.company_profile is None:
            return None
        profile = lead.company_profile
        if profile.tenant_id != tenant:
            return None
        evidence = {}

        def add(identifier, version):
            if not identifier or identifier in evidence:
                raise ValueError("Ambiguous retained evidence identifier")
            evidence[identifier] = version

        # A DB quote/URL alone is not an original-byte receipt. Admit indexed
        # public evidence only against its actual archived original/version.
        provenance = profile.provenance
        if provenance.get("origin") == "public_kb":
            source_id, source_version = provenance.get("source_id"), provenance.get("source_version")
            if isinstance(source_id, str) and isinstance(source_version, str):
                project = Path(__file__).resolve().parents[1]
                body = _read_beneath(project, "runtime_public_kb/archive/" + source_id + "/" + source_version)
                if _hash(body) != source_version:
                    return None
                original_text = body.decode("utf-8")
                for item in profile.evidence:
                    if (item.origin == "public_page_claim" and item.dataset_id == source_id
                            and (item.row_key or "").startswith(source_version + ":")
                            and item.quote and item.quote in original_text):
                        add(item.id, _json_hash({"original_sha256": source_version,
                                                "evidence": item.model_dump(mode="json")}))
        documents = store.get_documents_for_deal(tenant, room.deal_id) if room.deal_id else []
        for document in documents:
            if document.tenant_id != tenant or document.deal_id != room.deal_id:
                return None
            relative = Path(document.storage_uri).relative_to(UPLOAD_ROOT)
            if (relative.parts[:2] != (scope_component(tenant), scope_component(room.deal_id))
                    or len(relative.parts) < 3):
                return None
            original_sha = _hash(_read_beneath(UPLOAD_ROOT, relative.as_posix()))
            for block in document.blocks:
                if block.document_id != document.id:
                    return None
                version = _json_hash({"original_sha256": original_sha,
                    "document_id": document.id, "block": block.model_dump(mode="json")})
                add(block.id, version)
                add("private://" + document.id + "/" + block.id, version)
        # A source changed during resolution cannot borrow the earlier package
        # revision. Originals are otherwise immutable, server-scoped uploads.
        if revision_for(store, room) != evidence_revision:
            return None
        return BoundEvidenceInventory(tenant, room.id, evidence_revision, evidence)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def financial_reviewer_grants(conn, tenant, scope, as_of: date, *, reviewed_on=None):
    """Only active professionally qualified humans for this declared scope."""
    from delivery.compliance import QualifiedFinancialOwner
    from pydantic import ValidationError

    if scope is None or (reviewed_on is not None and (
            not isinstance(reviewed_on, date) or reviewed_on > as_of)):
        return set()
    rows = conn.execute("""SELECT q.user_id,q.qualification
        FROM auth_reviewer_qualifications q
        JOIN auth_memberships m ON m.tenant_id=q.tenant_id AND m.user_id=q.user_id
        JOIN auth_users u ON u.id=q.user_id
        WHERE q.tenant_id=? AND q.role='financial' AND q.active=1
          AND m.role='financial' AND m.active=1 AND u.disabled=0""", (tenant,)).fetchall()
    granted = set()
    for user_id, payload in rows:
        try:
            owner = QualifiedFinancialOwner.model_validate_json(payload)
        except (ValidationError, ValueError, TypeError):
            continue
        if (owner.reviewer_id == user_id and set(scope.jurisdictions) <= set(owner.jurisdictions)
                and scope.activity in owner.activities and owner.valid_from <= as_of <= owner.valid_until
                and (reviewed_on is None or owner.valid_from <= reviewed_on <= owner.valid_until)):
            granted.add(user_id)
    return granted
