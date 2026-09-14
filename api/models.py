"""
Request/response models that exist only to shape an API payload -- not
persisted entities, so they don't belong in schemas.py alongside the
Pydantic models store.py actually writes to disk.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

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


class WebSourceRequest(BaseModel):
    thesis: str = Field(min_length=3, max_length=2000)
    geography: Optional[str] = Field(default=None, max_length=120)
    seed_urls: list[str] = Field(default_factory=list, max_length=5)
    max_pages: int = Field(default=24, ge=1, le=30)
    max_companies: int = Field(default=5, ge=1, le=10)
    prepare_workflow: bool = True

    @field_validator("seed_urls")
    @classmethod
    def public_url_syntax(cls, urls):
        from agents.web_sources import normalize_url, SourceError
        try:
            return list(dict.fromkeys(normalize_url(url) for url in urls))
        except SourceError as exc:
            raise ValueError(str(exc)) from exc


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
