"""
Core data model — architecture doc §6.1 (entities) and §6.2 (extraction schema).

Every leaf in ExtractionResult carries source_block_id/source_page/confidence
so nothing reaches the memo without traceability (architecture doc §7,
CLAUDE.md guardrails). A field with no matching source stays null with
reason="not_found_in_source" — it is never inferred.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"


class DocBlock(BaseModel):
    id: str
    document_id: str
    page: int
    block_type: BlockType
    coordinates: dict[str, Any]
    content: Any  # str for text blocks, list[list[str]] for table blocks


class Document(BaseModel):
    id: str
    tenant_id: str
    deal_id: str
    filename: str
    type: str  # "pdf" | "xlsx"
    storage_uri: str
    blocks: list[DocBlock] = Field(default_factory=list)


class FieldStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class ExtractedValue(BaseModel):
    """One leaf value — architecture doc §6.2/§7, plus the review-audit
    fields from the ExtractedField entity in §6.1."""

    value: Optional[Any] = None
    unit: Optional[str] = None
    source_block_id: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Optional[float] = None
    extraction_method: Optional[str] = None
    reason: Optional[str] = None  # e.g. "not_found_in_source"
    status: FieldStatus = FieldStatus.PROPOSED
    reviewer: Optional[str] = None
    reviewed_at: Optional[str] = None
    edit_note: Optional[str] = None


class CapTableRow(BaseModel):
    holder: Optional[str] = None
    pct: Optional[float] = None
    share_class: Optional[str] = None


class FundingRound(BaseModel):
    round_name: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None
    lead_investor: Optional[str] = None
    # amount is a number and therefore needs the same mandatory-provenance
    # guardrail (§7 rule 1) as every scalar field -- a round without a valid
    # source_block_id is dropped by the Extraction Agent, not kept uncited.
    source_block_id: Optional[str] = None
    source_page: Optional[int] = None


class ExtractionResult(BaseModel):
    """Standard extraction schema — architecture doc §6.2."""

    tenant_id: str
    deal_id: str
    document_id: str
    arr: ExtractedValue = Field(default_factory=lambda: ExtractedValue(unit="USD"))
    arr_prior_year: ExtractedValue = Field(default_factory=lambda: ExtractedValue(unit="USD"))
    mrr: ExtractedValue = Field(default_factory=lambda: ExtractedValue(unit="USD"))
    growth_rate_yoy: ExtractedValue = Field(default_factory=lambda: ExtractedValue(unit="%"))
    burn_monthly: ExtractedValue = Field(default_factory=lambda: ExtractedValue(unit="USD"))
    cash_on_hand: ExtractedValue = Field(default_factory=lambda: ExtractedValue(unit="USD"))
    runway_months: ExtractedValue = Field(default_factory=ExtractedValue)
    headcount: ExtractedValue = Field(default_factory=ExtractedValue)
    cap_table: list[CapTableRow] = Field(default_factory=list)
    cap_table_source_block_id: Optional[str] = None
    cap_table_status: FieldStatus = FieldStatus.PROPOSED
    cap_table_reviewer: Optional[str] = None
    cap_table_reviewed_at: Optional[str] = None
    funding_history: list[FundingRound] = Field(default_factory=list)
    funding_history_status: FieldStatus = FieldStatus.PROPOSED
    funding_history_reviewer: Optional[str] = None
    funding_history_reviewed_at: Optional[str] = None
    extracted_at: str = Field(default_factory=utcnow)
    cross_check_flags: list[str] = Field(default_factory=list)


class LeadStatus(str, Enum):
    NEW = "new"
    REVIEWED = "reviewed"
    PROMOTED_TO_DEAL = "promoted_to_deal"
    DISMISSED = "dismissed"


class DiscoverySignal(BaseModel):
    """§6.1. A reason to *look at* a company, never a claim about its
    financials -- nothing here ever populates an ExtractedValue (§5.8)."""

    content: str
    source_url: Optional[str] = None
    source_type: str  # "github" | "data_gov_in" | "manual"
    discovered_at: str = Field(default_factory=utcnow)


class SourcedLead(BaseModel):
    """§6.1/§5.8. Output of the Deal Sourcing Agent -- distinct from Deal:
    a lead is a candidate nobody has submitted documents for yet. It only
    becomes a Deal once a human analyst deliberately promotes it."""

    id: str = Field(default_factory=lambda: new_id("lead"))
    tenant_id: str
    company_name: str
    sector_tag: Optional[str] = None
    discovery_signals: list[DiscoverySignal] = Field(default_factory=list)
    status: LeadStatus = LeadStatus.NEW
    promoted_deal_id: Optional[str] = None


class ResearchFinding(BaseModel):
    """§6.1. External corroboration/context, never blended into the same
    confidence tier as a cited financial figure from the deal's own
    documents (architecture doc §10.5) -- keep `status` visibly separate
    from ExtractedValue.status in how a memo presents it."""

    id: str = Field(default_factory=lambda: new_id("finding"))
    tenant_id: str
    deal_id: str
    topic: str
    content: str
    source_url: Optional[str] = None  # None for internal sector-notes findings
    source_type: str  # "github" | "hackernews" | "sec_edgar" | "wikipedia" | "internal_sector_notes" | "manual"
    retrieved_at: str = Field(default_factory=utcnow)
    status: FieldStatus = FieldStatus.PROPOSED


class ChartArtifact(BaseModel):
    """§6.1. Rendered deterministically by the Analytics Agent -- never by
    having a model describe a chart in prose (§5.6)."""

    id: str = Field(default_factory=lambda: new_id("chart"))
    tenant_id: str
    deal_id: str
    chart_type: str
    source_field_ids: list[str] = Field(default_factory=list)
    storage_uri: str


class MemoVersion(BaseModel):
    """§6.1. One finalized (or draft) memo produced by the Compilation Agent."""

    id: str = Field(default_factory=lambda: new_id("memo"))
    tenant_id: str
    deal_id: str
    version_number: int
    generated_at: str = Field(default_factory=utcnow)
    approved_by: Optional[str] = None
    content_uri: str
    # Real IB/VC practice uses three distinct documents, not one generic
    # memo (architecture doc §5.7 addendum): "teaser" (anonymized, 1-2pg,
    # pre-NDA), "cim" (full comprehensive memo, the original compile_memo
    # output), "proforma" (forward projection, explicitly labeled as such).
    document_type: str = "cim"


class DealStatus(str, Enum):
    """The pipeline-stage state machine the Planner/Supervisor Agent (§5.1)
    drives a deal through. Distinct from FieldStatus (a single field's
    review state) and LeadStatus (a sourcing candidate's state)."""

    NEW = "new"
    # A real engagement needs a signed mandate/term sheet before the shop
    # acts on a company's confidential documents (architecture §5.1
    # addendum, "Origination") -- ingestion is deliberately not reachable
    # from NEW directly.
    MANDATE_SIGNED = "mandate_signed"
    INGESTED = "ingested"
    EXTRACTED = "extracted"
    REVIEWED = "reviewed"  # is_ready_for_compilation() is true
    NEEDS_MANUAL_INPUT = "needs_manual_input"  # a rejected field exhausted its retries
    RESEARCHED = "researched"
    RESEARCH_REVIEWED = "research_reviewed"
    COMPILED = "compiled"


class Deal(BaseModel):
    """§6.1's top-level aggregate. Documents/ExtractedFields/etc. are stored
    as their own persisted rows (see store.py) keyed by (tenant_id, deal_id)
    rather than nested here, to avoid loading everything just to check
    status -- this record is deliberately just metadata + the state machine
    position."""

    id: str = Field(default_factory=lambda: new_id("deal"))
    tenant_id: str
    name: str
    stage: Optional[str] = None  # deal stage e.g. "Series A" -- not pipeline status
    status: DealStatus = DealStatus.NEW
    created_at: str = Field(default_factory=utcnow)
    document_ids: list[str] = Field(default_factory=list)
    # Origination (§5.1 addendum): the pitch-to-founder / RFP outcome. Kept
    # as simple deal-level metadata rather than a separate entity -- it's
    # 1:1 with the deal, same reasoning as not splitting DocBlock into its
    # own aggregate.
    mandate_type: Optional[str] = None  # e.g. "sell_side_advisory" | "vc_incubation"
    mandate_terms_summary: Optional[str] = None  # human-entered: fee %, exclusivity, etc.
    mandate_signed_at: Optional[str] = None


class InvestorContact(BaseModel):
    """§5's Roadshow stage (Stage 5 in the lifecycle mapped in CLAUDE.md's
    findings log): a lightweight demand-book row. Pure record-keeping for a
    human-led process -- this system tracks who was approached and their
    stated interest, it does not contact anyone or send anything itself."""

    id: str = Field(default_factory=lambda: new_id("investor"))
    tenant_id: str
    deal_id: str
    investor_name: str
    firm: Optional[str] = None
    teaser_sent_at: Optional[str] = None
    nda_status: str = "not_sent"  # "not_sent" | "sent" | "signed"
    cim_shared_at: Optional[str] = None
    interest_level: str = "new"  # "new" | "cold" | "warm" | "hot" | "passed" | "committed"
    notes: Optional[str] = None
    updated_at: str = Field(default_factory=utcnow)


class AuditEvent(BaseModel):
    """§6.1. One immutable record of a reviewer action on a field."""

    id: str = Field(default_factory=lambda: new_id("audit"))
    tenant_id: str
    deal_id: str
    actor: str
    action: str  # "approve" | "edit" | "reject" | "acknowledge_not_found"
    target_id: str  # field name, e.g. "arr", or "cap_table_row_2"
    timestamp: str = Field(default_factory=utcnow)
    before: Optional[Any] = None
    after: Optional[Any] = None
