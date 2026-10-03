"""L0 room activation and public-KB consumer contracts, before durable workers.

IDs/revisions are supplied by trusted services. These types do not authenticate
actors, establish source rights, or make privately derived facts public.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

from pydantic import Field, model_validator

from delivery.contracts import Contract, Digest, Identifier


class DealRoomActivated(Contract):
    event_type: Literal["DealRoomActivated"] = "DealRoomActivated"
    tenant_id: Identifier
    actor_id: Identifier
    workspace_id: Identifier
    input_revision: Digest
    workflow_version: Identifier
    max_seconds_per_pass: int = Field(default=120, gt=0, le=120)
    max_calls_per_pass: int = Field(default=6, gt=0, le=6)
    max_correction_passes: int = Field(default=3, ge=0, le=3)

    def idempotency_key(self) -> str:
        # Reopening the same room, even by a second authorized reviewer, is the
        # same work. Authorization must still be checked at enqueue and execution.
        scope = (self.event_type, self.tenant_id, self.workspace_id,
            self.input_revision, self.workflow_version)
        return hashlib.sha256(json.dumps(scope, separators=(",", ":")).encode()).hexdigest()


class PublicClaimReference(Contract):
    claim_id: Identifier
    source_revision: Digest
    company_id: Identifier
    source_policy_revision: Digest
    supporting_span_id: Identifier
    classification: Literal["public"] = "public"
    freshness: Literal["fresh", "stale", "unknown"]
    reuse: Literal["permitted", "blocked", "unresolved"]
    evidence_status: Literal["supported", "contradicted", "unresolved"]


class PublicKnowledgeRequest(Contract):
    # Intentionally no workspace, private prompt, upload, note or arbitrary
    # query field. Public company IDs must be resolved before this boundary.
    consumer: Literal["discovery", "room_context"]
    company_ids: tuple[Identifier, ...] = ()
    topics: tuple[Literal["identity", "funding", "investors", "market", "competitors", "benchmarks"], ...]
    eligibility_policy: Optional[Literal["global_research_v1", "india_preseed_seed_v1"]] = None

    @model_validator(mode="after")
    def distinguish_consumers(self):
        if not self.topics:
            raise ValueError("At least one public evidence topic is required")
        if self.consumer == "discovery" and self.eligibility_policy is None:
            raise ValueError("Discovery requires an explicit research policy")
        if self.consumer == "room_context" and (not self.company_ids or self.eligibility_policy is not None):
            raise ValueError("Room context requires resolved public identities without discovery filtering")
        return self


class PublicEvidenceBundle(Contract):
    bundle_revision: Digest
    claims: tuple[PublicClaimReference, ...]
    unresolved_conflict_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def unique_claims(self):
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("Duplicate claim references")
        return self
