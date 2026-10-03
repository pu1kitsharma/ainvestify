"""Local-model candidate assessment from rights-cleared, versioned public KB facts."""
from __future__ import annotations

import hashlib
import json
from datetime import date
import time
import re

from pydantic import BaseModel, ConfigDict, Field

from agents.inference.local_ollama import local_chat
from public_kb.claims import _entity_key


class CandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    status: str = Field(pattern="^(investigate|defer|exclude)$")
    reason: str = Field(min_length=25, max_length=600)


class CandidateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_source_id: str
    research_rationale: str = Field(min_length=50, max_length=1200)
    unresolved_questions: list[str] = Field(min_length=2, max_length=8)
    decisions: list[CandidateDecision] = Field(min_length=2, max_length=20)


def compare_public_candidates(kb, source_ids, *, model="qwen3.5:9b", review_feedback=None,
                              prior_response=None, capture=None):
    """Return a recorded proposal; deterministic gates still decide acceptance."""
    if not 2 <= len(source_ids) <= 20 or len(source_ids) != len(set(source_ids)):
        raise ValueError("Compare 2-20 distinct public sources")
    candidates = []
    for source_id in source_ids:
        kb.approved_source(source_id)
        row = kb.conn.execute("""SELECT f.last_sha256 FROM fetch_state f JOIN versions v
            ON v.source_id=f.source_id AND v.sha256=f.last_sha256
            WHERE f.source_id=? AND v.state='indexed'""", (source_id,)).fetchone()
        if row is None:
            raise ValueError("Candidate lacks a current indexed version")
        content = (kb.archive_root / source_id / row[0]).read_bytes()
        if hashlib.sha256(content).hexdigest() != row[0]:
            raise ValueError("Public candidate archive hash mismatch")
        record = json.loads(content)
        if record.get("source_format") != "startupdb_company_v1":
            raise ValueError("Unsupported public candidate source")
        entity_key = _entity_key(record["company"])
        projection = None
        claim_history = []
        if entity_key and kb.conn.execute("""SELECT 1 FROM sqlite_master WHERE type='table'
                AND name='public_company_projection'""").fetchone():
            current = kb.conn.execute("""SELECT stage,status,event_date,supporting_claim_ids,
                opposing_claim_ids,revision FROM public_company_projection WHERE entity_key=?""",
                (entity_key,)).fetchone()
            if current:
                projection = dict(stage=current[0], status=current[1], event_date=current[2],
                    supporting_claim_ids=json.loads(current[3]),
                    opposing_claim_ids=json.loads(current[4]), revision=current[5])
                policy_table = kb.conn.execute("""SELECT 1 FROM sqlite_master WHERE
                    type='table' AND name='refresh_policy'""").fetchone()
                if policy_table:
                    policies = kb.conn.execute("""SELECT p.source_id,p.next_due,p.last_error,p.active
                        FROM refresh_policy p WHERE p.source_id IN
                        (SELECT DISTINCT source_id FROM public_funding_claim WHERE entity_key=?)""",
                        (entity_key,)).fetchall()
                    tracked = {row[0] for row in policies}
                    all_sources = {row[0] for row in kb.conn.execute("""SELECT DISTINCT source_id
                        FROM public_funding_claim WHERE entity_key=?""", (entity_key,))}
                    projection["refresh_gaps"] = sorted((all_sources - tracked) | {
                        row[0] for row in policies if not row[3] or row[2] or row[1] <= time.time()})
                else:
                    projection["refresh_gaps"] = sorted(row[0] for row in kb.conn.execute(
                        "SELECT DISTINCT source_id FROM public_funding_claim WHERE entity_key=?",
                        (entity_key,)))
                claim_columns = {column[1] for column in kb.conn.execute(
                    "PRAGMA table_info(public_funding_claim)")}
                event_status_column = "event_status" if "event_status" in claim_columns else "'' AS event_status"
                claim_history = [dict(id=r[0], date=r[1], stage=r[2], source_id=r[3],
                    source_version=r[4], source_path=r[5], amount=r[6], currency=r[7],
                    amount_semantics=r[8], event_status=r[9]) for r in kb.conn.execute(f"""SELECT id,event_date,stage,
                    source_id,source_sha256,source_path,amount,currency,amount_semantics,
                    {event_status_column} FROM public_funding_claim WHERE entity_key=?
                    ORDER BY event_date DESC,id""",
                    (entity_key,)).fetchall()]
        candidates.append({"source_id": source_id, "version": row[0], "company": record["company"],
            "reconciled_current": projection, "claim_history": claim_history,
            "rounds": [{"label": r["label"], "date": r["date"],
                        "date_precision": r.get("date_precision"), "status": r.get("status"),
                        "amount": r["amount"],
                        "source_count": len(r["source_urls"])} for r in record["funding_history"]]})
    instructions = (f"As of {date.today().isoformat()}, you are screening REAL public companies for further diligence in Indian pre-seed/seed startup fundraising. "
        "Use only the supplied StartupDB source-reported facts. Compare every candidate. Choose ONE company to investigate, "
        "or use selected_source_id='none' if none is supported. This is not an investment recommendation. "
        "A missing revenue or operating-status fact is a diligence gap, not by itself a reason to exclude a sample research candidate. "
        "A past reported funding date is not evidence that a round remains open; do not call it active. "
        "Treat every source field as publisher-reported, not independently confirmed. "
        "Never mention a prior response, correction, review feedback or this instruction in the investment rationale. "
        "A later-stage round excludes a current seed prospect even if a seed entry also appears. "
        "The reconciled current projection and claim history supersede a stale source listing. "
        "Unknown or non-Indian headquarters does not establish Indian eligibility. "
        "A funding round does not prove operating traction, valuation, technology, or investability. "
        "Explain the business reason for investigation and specific missing diligence in concise decision rationales. "
        "Do not invent product or financial facts. Return JSON matching the schema.")
    ids = {item["source_id"] for item in candidates}
    deadline = time.monotonic() + 120
    feedback = list(review_feedback or [])
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise TimeoutError("Public candidate assessment exhausted its 120-second budget")
        user_content = json.dumps({"candidates": candidates,
            "prior_response": prior_response, "review_feedback": feedback}, sort_keys=True)
        response = local_chat(model=model, messages=[{"role": "system", "content": instructions},
            {"role": "user", "content": user_content}],
            format=CandidateAssessment.model_json_schema(), options={"temperature": 0},
            think=False, timeout_seconds=remaining)
        raw = response["message"]["content"]
        if capture is not None:
            capture({"attempt": attempt + 1, "model": model, "candidate_versions":
                     {item["source_id"]: item["version"] for item in candidates},
                     "raw_response": raw})
        try:
            assessment = CandidateAssessment.model_validate_json(raw)
        except ValueError as exc:
            issue = "Response does not match the candidate assessment schema"
            schema_error = exc
        else:
            schema_error = None
            chosen = assessment.selected_source_id
            decisions = {decision.source_id: decision for decision in assessment.decisions}
            missing = sorted(ids - set(decisions))
            extra = sorted(set(decisions) - ids)
            if missing or extra or len(assessment.decisions) != len(ids):
                issue = f"Assess every source exactly once; missing IDs: {missing}; unexpected IDs: {extra}"
            elif chosen != "none" and chosen not in ids:
                issue = "Selected source ID is not among the supplied candidates"
            elif chosen != "none" and decisions[chosen].status != "investigate":
                issue = "Selected source must have an investigate decision"
            else:
                unsupported_exclusions = [item["source_id"] for item in candidates
                    if decisions[item["source_id"]].status == "exclude"
                    and any(place in item["company"].get("headquarters_location", "").lower()
                            for place in ("india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "pune", "chennai"))
                    and item["rounds"]
                    and all(round_["label"].lower() in {"seed", "pre-seed", "pre seed"}
                            for round_ in item["rounds"])
                    and item["company"].get("operating_status", "").lower()
                            not in {"closed", "inactive", "acquired", "dissolved"}]
                if unsupported_exclusions:
                    issue = ("A reported historical Seed or Pre-Seed round alone does not establish a later stage. "
                             "Reconsider unsupported exclusions for source IDs "
                             f"{sorted(unsupported_exclusions)}; use defer when current stage is unknown.")
                else:
                    issue = None
                selected = next((item for item in candidates if item["source_id"] == chosen), None)
                if selected and issue is None:
                    location = selected["company"].get("headquarters_location", "").lower()
                    rounds = selected["rounds"]
                    projection = selected["reconciled_current"]
                    if projection and (projection["status"] != "current_source_reported"
                                       or (projection["stage"] or "").lower() not in {"seed", "pre-seed", "pre seed"}):
                        issue = "Reconciled current company history does not support a seed-stage selection"
                    elif projection and projection["refresh_gaps"]:
                        issue = "Reconciled company evidence has overdue, failed or untracked public refreshes"
                    elif not any(place in location for place in ("india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "pune", "chennai")):
                        issue = "Selected company's Indian location is unsupported by the indexed source"
                    elif not rounds or any(r["label"].lower() not in {"seed", "pre-seed", "pre seed"} for r in rounds):
                        issue = "Selected company has an unqualified later-stage history"
                    else:
                        issue = None
                if issue is None:
                    prose = [assessment.research_rationale,
                             *(decision.reason for decision in assessment.decisions)]
                    if any(re.search(r'\b(?:prior response|previous response|review feedback|correction feedback)\b', text, re.I)
                           for text in prose):
                        issue = "Write source-grounded investment rationales without discussing prior responses or review feedback"
                    elif any(re.search(r'\b(?:confirmed|verified)\s+(?:Indian\s+)?(?:headquarters|location|funding|revenue|traction)\b', text, re.I)
                             for text in prose):
                        issue = "Publisher-reported records do not independently confirm company facts; qualify source claims"
                if issue is None:
                    for item in candidates:
                        decision = decisions[item["source_id"]]
                        text = decision.reason + (' ' + assessment.research_rationale
                            if chosen == item["source_id"] else '')
                        if (re.search(r'\b(?:active fundraising|currently raising|open (?:funding )?round|seeking (?:a )?series [a-z])\b', text, re.I)
                                and not any(str(round_.get("status", "")).lower() in
                                    {"open", "raising", "active"} for round_ in item["rounds"])):
                            issue = ("A dated reported round does not establish current fundraising availability "
                                     f"for source ID {item['source_id']}; remove unsupported status claims")
                            break
        if issue is None:
            return {"model": model, "model_response": raw, "assessment": assessment.model_dump(),
                    "candidate_versions": {item["source_id"]: item["version"] for item in candidates},
                    "validation": "structural_and_scope_gates_passed", "review_feedback": feedback}
        if attempt == 2:
            raise ValueError(issue) from schema_error
        prior_response = raw
        feedback.append(issue)
    raise RuntimeError("Unreachable candidate assessment state")
