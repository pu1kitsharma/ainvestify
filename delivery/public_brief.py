"""One bounded local-model research brief from a rights-cleared public KB version."""
from __future__ import annotations

from datetime import date
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from agents.inference.local_ollama import local_chat


class BriefSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str = Field(min_length=5, max_length=100)
    text: str = Field(min_length=50, max_length=1200)
    source_ids: list[str] = Field(min_length=1, max_length=5)


class PublicBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: list[BriefSection] = Field(min_length=3, max_length=6)
    decision: str = Field(min_length=40, max_length=500)


def draft_public_brief(kb, source_id, *, model="qwen3.5:9b", review_feedback=None,
                       prior_response=None):
    url = kb.approved_source(source_id)
    row = kb.conn.execute("""SELECT f.last_sha256 FROM fetch_state f JOIN versions v
        ON v.source_id=f.source_id AND v.sha256=f.last_sha256
        WHERE f.source_id=? AND v.state='indexed'""", (source_id,)).fetchone()
    if not row:
        raise ValueError("Current indexed KB version required")
    digest = row[0]
    content = (kb.archive_root / source_id / digest).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Public KB version hash mismatch")
    record = json.loads(content)
    if record.get("source_format") != "startupdb_company_v1":
        raise ValueError("Unsupported public KB source")
    # URL slugs can contain descriptive words but are not evidence that the
    # linked articles were read. Keep them in the archive for attribution,
    # outside the model's factual context.
    inference_record = {**record, "funding_history": [
        {key: value for key, value in round_.items() if key != "source_urls"}
        for round_ in record.get("funding_history", [])]}
    instructions = (f"Today is {date.today().isoformat()}. Write a sample diligence brief for a real startup, "
        "using ONLY this rights-cleared StartupDB structured record. All substantive prose must be your own. "
        "Explain the reported source facts, their limited decision value, and concrete investigation questions. "
        "A past funding date does not establish whether fundraising remains open or closed. "
        "The publisher's reported round is not proof that cash entered the company. "
        "A blank field is unpopulated, not explicitly labeled unknown. Listed source URLs are links, not article content. "
        "Do not infer a product, customer traction, technology performance, valuation, revenue, profitability, "
        "legal entity, or investment merit when those data are absent. Label missing data as unknown. "
        "This is a draft for a sample deal room, not investor-ready advice. "
        "Every section must cite the supplied source_id exactly. "
        "If review_feedback is provided, inspect every prior sentence and rewrite any sentence it flags; "
        "do not copy a rejected claim into a new draft. Return only JSON matching the schema.")
    answer = local_chat(model=model, messages=[{"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps({"source_id": source_id, "url": url,
            "version": digest, "record": inference_record, "prior_response": prior_response,
            "review_feedback": review_feedback or []}, sort_keys=True)}],
        format=PublicBrief.model_json_schema(), options={"temperature": 0}, think=False)
    raw = answer["message"]["content"]
    brief = PublicBrief.model_validate_json(raw)
    if any(section.source_ids != [source_id] for section in brief.sections):
        raise ValueError("Brief cited an unsupplied source")
    return {"model": model, "source_id": source_id, "source_url": url,
        "source_version": digest, "model_response": raw, "brief": brief.model_dump(),
        "validation": "structural_and_citation_scope_passed", "claim_review_status": "pending",
        "review_feedback": review_feedback or []}
