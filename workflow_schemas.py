"""Dataset provenance and evidence-driven operating workspace (architecture §16)."""
from typing import Literal, Optional
from pydantic import BaseModel, Field
from schemas import new_id, utcnow


class DatasetSource(BaseModel):
    id: str
    name: str
    url: str
    publisher: str
    granularity: Literal["company", "aggregate"]
    geography: str
    license_name: str
    terms_url: str
    access: Literal["open", "metadata_only", "authorized_import"]
    checked_at: str
    refresh_days: int = 30
    attribution: str
    limitation: str


class DatasetRecord(BaseModel):
    key: str
    values: dict[str, str]
    source_url: str
    observed_at: Optional[str] = None


class DatasetSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dataset"))
    tenant_id: str
    source_id: str
    query: str
    records: list[DatasetRecord] = Field(default_factory=list)
    status: str = "available"
    coverage: str = "bounded_query"
    content_hash: str = ""
    retrieved_at: str = Field(default_factory=utcnow)
    detail: str = ""


class ControlCheck(BaseModel):
    id: str
    title: str
    status: Literal["satisfied", "needs_evidence", "needs_review", "not_applicable"]
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    authority_urls: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)
    policy_version: str = "india-pilot-2026-09-13"


class WorkItem(BaseModel):
    id: str
    stage: str
    title: str
    status: Literal["completed", "ready", "blocked", "needs_input"]
    reason: str
    dependency_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class PlanTask(BaseModel):
    action: str = Field(min_length=12, max_length=500)
    deliverable: str = Field(min_length=12, max_length=400)
    required_inputs: list[str] = Field(min_length=1, max_length=4)
    success_measure: str = Field(min_length=12, max_length=400)


class AnalysisSection(BaseModel):
    heading: str = Field(min_length=5, max_length=100)
    content: str = Field(min_length=60, max_length=1600)
    evidence_ids: list[str] = Field(min_length=1, max_length=4)


class OperationDraft(BaseModel):
    stage: Literal["diligence", "incubation", "documents", "fundraising"]
    title: str = Field(max_length=180)
    actions: list[str] = Field(default_factory=list, max_length=6)
    tasks: list[PlanTask] = Field(default_factory=list, max_length=3)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    unknowns: list[str] = Field(default_factory=list, max_length=8)
    sections: list[AnalysisSection] = Field(default_factory=list, max_length=4)
    decision: str = ""


class DraftPack(BaseModel):
    drafts: list[OperationDraft] = Field(min_length=4, max_length=4)


class WorkspaceAttestation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("attestation"))
    kind: Literal["source_rights_review", "identity_review", "engagement_authority", "regulatory_scope", "privacy_basis",
                  "commercial_validation", "financial_review", "incubation_outcomes", "investor_qualification",
                  "release_approval", "signed_documents", "funds_received"]
    note: str = Field(min_length=12, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    reviewer: str
    recorded_at: str = Field(default_factory=utcnow)
    basis_hash: str


class AutomationRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("automation"))
    status: Literal["queued", "running", "completed", "failed", "interrupted"] = "queued"
    phase: str = "Waiting for local worker"
    model: str
    worker_id: str
    started_at: str = Field(default_factory=utcnow)
    completed_at: Optional[str] = None
    error: Optional[str] = None


class OperatingWorkspace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("workspace"))
    tenant_id: str
    lead_id: str
    company_id: str
    company_name: str
    geography: Optional[str] = None
    thesis: str = ""
    revision: int = 0
    basis_hash: str = ""
    evaluated_at: str = Field(default_factory=utcnow)
    controls: list[ControlCheck] = Field(default_factory=list)
    work_items: list[WorkItem] = Field(default_factory=list)
    drafts: list[OperationDraft] = Field(default_factory=list)
    draft_basis_hash: str = ""
    draft_stage_basis: dict[str, str] = Field(default_factory=dict)
    draft_status: str = "not_generated"
    draft_schema_version: int = 1
    model: Optional[str] = None
    research: dict = Field(default_factory=dict)
    analysis_review: dict = Field(default_factory=dict)
    preparation: dict = Field(default_factory=dict)
    investment_case: dict = Field(default_factory=dict)
    investment_case_history: list[dict] = Field(default_factory=list)
    company_brief: dict = Field(default_factory=dict)
    company_brief_attempts: list[dict] = Field(default_factory=list)
    company_brief_history: list[dict] = Field(default_factory=list)
    metric_imports: list[dict] = Field(default_factory=list)
    metric_updates: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    automation: Optional[AutomationRun] = None
    attestations: list[WorkspaceAttestation] = Field(default_factory=list)
    events: list[dict[str, str]] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=lambda: {
        "internal_research": True, "draft_preparation": True,
        "external_sending": False, "signing": False, "moving_money": False})
