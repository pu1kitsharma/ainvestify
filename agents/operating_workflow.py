"""Reconcile evidence, run policy checks, and prepare bounded operating drafts.

Work completion is derived from evidence and explicit attestations. LLM output
cannot change gates, move investor stages, send messages or declare a close.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from agents.local_models import PreparationModel as LocalModel
from agents.datasets import SOURCE_BY_ID
from schemas import utcnow
from workflow_schemas import ControlCheck, OperatingWorkspace, WorkItem

AUTHORITY = {
    "intermediary": "https://www.sebi.gov.in/legal/master-circulars/jul-2026/master-circular-for-merchant-bankers_102815.html",
    "companies": "https://www.indiacode.nic.in/handle/123456789/2114?locale=en",
    "privacy": "https://www.meity.gov.in/static/uploads/2025/11/c56ceae6c383460ca69577428d36828b.pdf",
}
POLICY_REVIEW_BY = "2026-10-13"
CURRENT_DRAFT_VERSION = 4


def evidence_is_fresh(evidence):
    """Missing, invalid or timezone-ambiguous timestamps require review."""
    try:
        retrieved = datetime.fromisoformat(evidence.retrieved_at.replace("Z", "+00:00"))
        if retrieved.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - retrieved).total_seconds()
        return 0 <= age <= 90 * 86400
    except (ValueError, TypeError):
        return False


def workspace_basis(store, lead):
    documents = []
    extraction = None
    if lead.promoted_deal_id:
        deal = store.get_deal(lead.tenant_id, lead.promoted_deal_id)
        if deal:
            for doc_id in deal.document_ids:
                doc = store.get_document(lead.tenant_id, doc_id)
                if doc: documents.append(doc)
            extraction = store.get_extraction_result(lead.tenant_id, deal.id)
    profile = lead.company_profile
    canonical = {"company": profile.model_dump(exclude={"updated_at", "assessment", "discovery_source_url", "criteria_review", "growth_analysis"}),
                 "documents": [d.model_dump() for d in documents],
                 "extraction": extraction.model_dump() if extraction else None}
    existing = store.get_workspace(lead.tenant_id, lead_id=lead.id)
    if existing and existing.metric_updates:
        canonical["metric_updates"] = existing.metric_updates
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    valid = {e.id for e in profile.evidence} | {"doc:" + d.id for d in documents}
    return digest, valid, documents, extraction


def reconcile_workspace(store, lead, geography=None, thesis=None, persist=True):
    if not lead.company_profile:
        raise ValueError("A company evidence profile is required to create an operating workspace.")
    workspace = store.get_workspace(lead.tenant_id, lead_id=lead.id)
    expected = workspace.revision if workspace else None
    if workspace is None:
        workspace = OperatingWorkspace(tenant_id=lead.tenant_id, lead_id=lead.id, company_id=lead.company_id or lead.company_profile.id,
                                       company_name=lead.company_name, geography=geography, thesis=thesis or "")
    profile = lead.company_profile
    basis, valid, documents, extraction = workspace_basis(store, lead)
    changed = bool(workspace.basis_hash and workspace.basis_hash != basis)
    if changed:
        workspace.events.append({"at": utcnow(), "action": "evidence_changed", "detail": "Drafts and prior attestations require re-evaluation."})
    workspace.basis_hash = basis
    workspace.evaluated_at = utcnow()
    attestations = {a.kind: a for a in workspace.attestations if a.basis_hash == basis and set(a.evidence_ids).issubset(valid)}
    partial_current = workspace.draft_status == "partial" and any(b == basis for b in workspace.draft_stage_basis.values())
    if workspace.drafts and ((workspace.draft_basis_hash != basis and not partial_current) or workspace.draft_schema_version < CURRENT_DRAFT_VERSION):
        workspace.draft_status = "stale"
    fields = {e.field for e in profile.evidence}
    business = bool(fields & {"offering", "business_model", "traction"})
    fresh = bool(profile.evidence) and all(evidence_is_fresh(e) for e in profile.evidence)
    license_unknown = any(e.dataset_id and (e.dataset_id not in SOURCE_BY_ID or SOURCE_BY_ID[e.dataset_id].access != "open") for e in profile.evidence)
    web_rights_unknown = any(e.origin == "public_page_claim" for e in profile.evidence) and "source_rights_review" not in attestations
    rights_pending = license_unknown or web_rights_unknown
    controls = [
        ControlCheck(id="source_rights", title="Dataset access and permitted use", status="needs_review" if rights_pending else "satisfied",
            reason="Dataset or public-web reuse rights need review before release." if rights_pending else "Dataset licenses or a source-rights review are recorded for this evidence version.",
            blocks=["release", "fundraising"] if rights_pending else []),
        ControlCheck(id="freshness", title="Evidence freshness", status="satisfied" if fresh else "needs_review",
            reason="Retrieval age within the 90-day pilot policy; observation dates still require review." if fresh else "One or more sources need refresh; cached retrieval is not current verification.", blocks=[] if fresh else ["release"]),
        ControlCheck(id="deployment", title="External execution", status="needs_review",
            reason="Local pilot: authenticated roles, authorized sharing and external integrations are not enabled.",
            blocks=["send", "sign", "transfer"]),
    ]
    india = "india" in (workspace.geography or "").casefold() or any(e.field == "location" and "india" in e.value.casefold() for e in profile.evidence)
    requirements = [
        ("identity_review", "Company identity and beneficial-ownership diligence", ["incubation", "release"], [AUTHORITY['companies']]),
        ("engagement_authority", "Engagement mandate and authority to act", ["incubation", "release", "fundraising"], []),
        ("regulatory_scope", "Jurisdiction, intermediary role and offering-route review", ["release", "fundraising", "closing"], [AUTHORITY['intermediary'], AUTHORITY['companies']]),
        ("privacy_basis", "Purpose, personal-data basis, retention and sharing review", ["release", "fundraising"], [AUTHORITY['privacy']]),
        ("commercial_validation", "Customer and market validation", ["readiness"], []),
        ("financial_review", "Reconciled financials and approved assumptions", ["readiness", "release"], []),
        ("incubation_outcomes", "Measured incubation outcomes", ["readiness"], []),
        ("investor_qualification", "Evidence of investor fit and pipeline activity", ["fundraising"], []),
        ("release_approval", "Approval of the current materials", ["release", "fundraising"], []),
        ("signed_documents", "Executed documents and closing conditions", ["closing"], [AUTHORITY['companies']]),
        ("funds_received", "Evidence of funds received", ["closing"], []),
    ]
    for key, title, blocks, urls in requirements:
        record = attestations.get(key)
        reason = f"Recorded by {record.reviewer}; tied to this evidence version." if record else "Accountable review and supporting company document evidence are missing."
        if key == "regulatory_scope" and not record:
            reason = "Determine issuer/company jurisdiction, advisory versus fund-manager role, instrument, investor residency and applicable registrations; no blanket VC/IB exemption is assumed."
        if key == "privacy_basis" and not record:
            reason = "Record lawful purpose, necessary data, retention and permitted recipients." + (" DPDP commencement is phased; this is a readiness control, not a statement that every provision is in force." if india else " Jurisdiction-specific privacy rules require review.")
        if key == "identity_review" and not record:
            reason = "A dataset identifier or DPIIT recognition is not proof of current MCA standing, ownership, operating activity or investment suitability."
        controls.append(ControlCheck(id=key, title=title, status="satisfied" if record else "needs_evidence",
            reason=reason, evidence_ids=record.evidence_ids if record else [], authority_urls=urls if india else [], blocks=[] if record else blocks))
    if datetime.now(timezone.utc).date().isoformat() > POLICY_REVIEW_BY:
        controls.append(ControlCheck(id="policy_currency", title="Policy references need review", status="needs_review",
            reason=f"Pilot policy review was due {POLICY_REVIEW_BY}. Revalidate current rules before release.", blocks=["release", "fundraising", "closing"]))
    from agents.company_metrics import metrics_report
    workspace.metrics = metrics_report(workspace.metric_updates)
    workspace.controls = controls
    from agents.transaction_workpaper import preparation_workpaper
    workspace.preparation = preparation_workpaper(lead, documents, extraction, controls)
    blocked = lambda action: [c.title for c in controls if action in c.blocks]
    pack_current = bool(workspace.drafts and workspace.draft_status == "draft" and workspace.draft_basis_hash == basis)
    tasks = [
        WorkItem(id="source", stage="sourcing", title="Assemble company dossier", status="completed" if business and profile.website else "needs_input",
            reason="Public/dataset claims assembled; verification status remains visible." if business and profile.website else "Resolve website and business evidence before qualification.", evidence_ids=[e.id for e in profile.evidence]),
        WorkItem(id="diligence", stage="diligence", title="Prepare diligence questions and evidence gaps", status="completed" if pack_current else "ready" if business else "blocked",
            reason="Current draft prepared." if pack_current else "Generate from cited facts." if business else "Insufficient business evidence; do not infer from company name.", dependency_ids=["source"]),
        WorkItem(id="incubation", stage="incubation", title="Execute incubation milestones", status="blocked" if blocked("incubation") else "completed" if "incubation_outcomes" in attestations else "ready",
            reason="; ".join(blocked("incubation")) or "Plan can proceed under the recorded mandate; completion requires measured outcomes.", dependency_ids=["diligence"]),
        WorkItem(id="readiness", stage="incubation", title="Assess market and investment readiness", status="blocked" if blocked("readiness") else "completed",
            reason="; ".join(blocked("readiness")) or "Commercial and financial reviews recorded; no funding guarantee.", dependency_ids=["incubation"]),
        WorkItem(id="release", stage="documents", title="Validate materials for release", status="blocked" if blocked("release") or not pack_current else "completed",
            reason="; ".join(blocked("release")) or "Prepare and approve the current draft pack.", dependency_ids=["readiness"]),
        WorkItem(id="fundraising", stage="fundraising", title="Investor qualification and fundraising preparation", status="blocked" if blocked("fundraising") else "completed",
            reason="; ".join(blocked("fundraising")) or "Internal preparation enabled. Sending remains disabled.", dependency_ids=["release"]),
        WorkItem(id="closing", stage="fundraising", title="Confirm closing evidence", status="blocked" if blocked("closing") else "completed",
            reason="; ".join(blocked("closing")) or "Executed-document and received-funds attestations recorded; software did not move money.", dependency_ids=["fundraising"]),
    ]
    # Dependencies are evaluated, not merely displayed as a decorative checklist.
    for task in tasks:
        unmet = [dep for dep in task.dependency_ids if next(t for t in tasks if t.id == dep).status != "completed"]
        if unmet and task.status != "blocked":
            task.status = "blocked"
            task.reason = "Upstream work incomplete: " + ", ".join(unmet) + ". " + task.reason
    workspace.work_items = tasks
    if persist:
        store.save_workspace(workspace, expected_revision=expected)
    return workspace


def prepare_operating_drafts(store, lead, model=None):
    workspace = reconcile_workspace(store, lead)
    profile = lead.company_profile
    if not any(e.field in {"offering", "business_model", "traction"} for e in profile.evidence):
        raise ValueError("Business evidence is missing. Research must establish what the company does before drafting a plan.")
    if workspace.draft_basis_hash == workspace.basis_hash and workspace.draft_status == "draft":
        return workspace
    model = model or LocalModel()
    basis = workspace.basis_hash
    business_facts = [e for e in profile.evidence if e.field in {"offering", "business_model", "traction", "customer", "pricing", "product", "team"}]
    aliases = {f"C{i}": evidence.id for i, evidence in enumerate(business_facts, 1)}
    company_payload = {"name": profile.name, "website": profile.website,
        "evidence": [{"id": alias, "field": e.field, "passage": e.quote, "source_url": e.source_url,
                      "status": "Unverified public-page statement; may include illustrative product demos."}
                     for alias, e in zip(aliases, business_facts)]}
    payload = json.dumps({"COMPANY": company_payload,
        "SCOPE": "Analyze the observed business, not the discovery query. A depicted workflow is not a testimonial or actual customer result.",
        "PREPARATION_WORKPAPER": workspace.preparation,
        "AVAILABLE_EVIDENCE_IDS": list(aliases), "RESEARCH_LIMITATIONS": workspace.research.get("limitations", "Only public business claims collected; no financial/customer verification.")})
    from agents.business_analysis import prepare_analysis
    comparisons = profile.growth_analysis.get('comparisons', [])
    growth_summary = ('Source-reported annual comparisons: ' + '; '.join(f"{c['metric']}: {c['change_pct']:+g}% ({c['period_before']} to {c['period_after']})" for c in comparisons) + '. These figures have not been independently audited.') if comparisons else 'The collected evidence contains no validated recent annual company operating comparison. Product promises, demo figures and customer benefits cannot establish company growth. This is an evidence gap, not proof of no growth. Revenue/paid-customer figures for comparable dated periods are needed.'

    if workspace.draft_schema_version < CURRENT_DRAFT_VERSION:
        workspace.draft_stage_basis = {}
    stages = ("diligence", "incubation", "documents", "fundraising")
    for index, stage in enumerate(stages):
        if workspace.draft_schema_version >= CURRENT_DRAFT_VERSION and workspace.draft_stage_basis.get(stage) == basis and any(d.stage == stage and d.tasks for d in workspace.drafts):
            continue
        if workspace.automation:
            workspace.automation.phase = f"Writing {stage} analysis ({index+1} of 4)"
            store.save_workspace(workspace, expected_revision=workspace.revision)
        feedback = ''
        for attempt in range(2):
            try:
                draft = prepare_analysis(model, stage, payload, aliases, growth_summary, feedback)
                break
            except Exception as exc:
                if attempt:
                    reason = str(exc) if isinstance(exc, ValueError) and str(exc) in {'unsupported analysis citation', 'unsupported business citations or incomplete task specifications'} else type(exc).__name__
                    raise ValueError(f"The {stage} plan could not be validated ({reason}); completed plans are saved. Retry resumes missing stages.") from exc
                feedback = str(exc)[:700] if isinstance(exc, ValueError) else 'Return all required fields with complete concise answers and permitted citations.'
        current_lead = store.get_lead(lead.tenant_id, lead.id)
        latest = store.get_workspace(lead.tenant_id, workspace_id=workspace.id)
        if workspace_basis(store, current_lead)[0] != basis or latest.revision != workspace.revision:
            raise ValueError("Evidence/workspace changed during generation. Completed work is retained; update plans against current evidence.")
        workspace.drafts = [d for d in workspace.drafts if d.stage != stage] + [draft]
        workspace.analysis_review = {}
        workspace.draft_stage_basis[stage] = basis
        workspace.draft_status = "partial"
        workspace.draft_schema_version = CURRENT_DRAFT_VERSION
        workspace.model = model.name
        workspace.events.append({"at": utcnow(), "action": "plan_prepared", "detail": f"{stage.capitalize()} plan saved with a decision, cited analysis and next task."})
        store.save_workspace(workspace, expected_revision=workspace.revision)
    workspace.draft_basis_hash = basis
    workspace.draft_status = "draft"
    workspace.draft_schema_version = CURRENT_DRAFT_VERSION
    workspace.model = model.name
    workspace.events.append({"at": utcnow(), "action": "draft_pack_prepared", "detail": "Four internal drafts; release and execution gates unchanged."})
    store.save_workspace(workspace, expected_revision=workspace.revision)
    return reconcile_workspace(store, store.get_lead(lead.tenant_id, lead.id))
