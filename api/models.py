"""
Request/response models that exist only to shape an API payload -- not
persisted entities, so they don't belong in schemas.py alongside the
Pydantic models store.py actually writes to disk.
"""
from typing import Optional

from pydantic import BaseModel

from agents.review_checkpoint import ReviewDecisionOutcome
from schemas import Deal, ExtractionResult


class ReviewPayload(BaseModel):
    """Aggregated GET .../review response (plan §2): everything the
    single-screen review UI needs in one call instead of stitching together
    several requests."""

    extraction_result: Optional[ExtractionResult]
    ready_for_compilation: bool
    cross_check_flags: list[str]


class FieldDecisionRequest(BaseModel):
    decision: str  # "approve" | "edit" | "reject" | "acknowledge"
    new_value: Optional[str] = None
    note: Optional[str] = None
    model: str = "phi4-mini"  # only used if decision == "reject" triggers a retry


class BlockDecisionRequest(BaseModel):
    """Shared shape for cap-table/funding-history decisions -- no
    new_value, since both are reviewed as one unit, never edited inline."""

    decision: str  # "approve" | "reject" | "acknowledge"
    note: Optional[str] = None
    model: str = "phi4-mini"


class FieldDecisionResponse(BaseModel):
    outcome: ReviewDecisionOutcome
    extraction_result: ExtractionResult
    deal: Deal


class SourceLeadsRequest(BaseModel):
    sector_keyword: str
    location_filter: Optional[str] = None


class LeadDecisionRequest(BaseModel):
    decision: str  # "keep" | "dismiss"


class PromoteLeadRequest(BaseModel):
    name: Optional[str] = None


class CreateDealRequest(BaseModel):
    name: str
    stage: Optional[str] = None


class SignMandateRequest(BaseModel):
    mandate_type: str
    terms_summary: str


class ExtractRequest(BaseModel):
    model: str = "phi4-mini"
    reviewer_feedback: Optional[str] = None


class DirectiveRequest(BaseModel):
    directive: str


class PromptRequest(BaseModel):
    prompt: str


class RunResearchRequest(BaseModel):
    company_name: str
    sector_query: Optional[str] = None


class FindingDecisionRequest(BaseModel):
    decision: str  # "approve" | "reject"


class AddInvestorRequest(BaseModel):
    investor_name: str
    firm: Optional[str] = None
    nda_status: str = "not_sent"
    interest_level: str = "new"
    notes: Optional[str] = None
