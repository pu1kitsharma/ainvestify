import pytest
from pydantic import ValidationError

from delivery.workflow_contracts import DealRoomActivated, PublicClaimReference, PublicKnowledgeRequest


def activation(**changes):
    data = dict(tenant_id="owner", actor_id="user", workspace_id="room",
        input_revision="a" * 64, workflow_version="v1")
    data.update(changes)
    return DealRoomActivated(**data)


def test_unchanged_reopen_has_same_work_key():
    assert activation().idempotency_key() == activation(actor_id="authorized-reviewer").idempotency_key()


@pytest.mark.parametrize("change", [dict(tenant_id="other"), dict(workspace_id="other"),
    dict(input_revision="b" * 64), dict(workflow_version="v2")])
def test_changed_scope_or_input_never_reuses_work(change):
    assert activation().idempotency_key() != activation(**change).idempotency_key()


@pytest.mark.parametrize("change", [dict(max_seconds_per_pass=121), dict(max_calls_per_pass=7),
    dict(max_correction_passes=4), dict(max_seconds_per_pass=0)])
def test_unbounded_activation_rejected(change):
    with pytest.raises(ValidationError):
        activation(**change)


def test_discovery_requires_eligibility_but_context_does_not():
    with pytest.raises(ValidationError):
        PublicKnowledgeRequest(consumer="discovery", topics=("funding",))
    PublicKnowledgeRequest(consumer="discovery", topics=("funding",),
        eligibility_policy="india_preseed_seed_v1")
    PublicKnowledgeRequest(consumer="discovery", topics=("funding",),
        eligibility_policy="global_research_v1")
    PublicKnowledgeRequest(consumer="room_context", company_ids=("resolved-comparable",), topics=("market",))
    with pytest.raises(ValidationError):
        PublicKnowledgeRequest(consumer="room_context", topics=("market",))


def test_private_fields_cannot_be_added_to_public_request():
    with pytest.raises(ValidationError):
        PublicKnowledgeRequest(consumer="room_context", company_ids=("company",),
            topics=("benchmarks",), private_notes="synthetic-private-canary")


def test_private_claim_classification_rejected():
    with pytest.raises(ValidationError):
        PublicClaimReference(claim_id="claim", source_revision="a" * 64, company_id="company",
            source_policy_revision="b" * 64, supporting_span_id="span", classification="private",
            freshness="fresh", reuse="permitted", evidence_status="supported")


def test_discovery_contract_matches_existing_policy():
    from agents.discovery.eligibility import GLOBAL_POLICY, POLICY
    for policy in (GLOBAL_POLICY, POLICY):
        request = PublicKnowledgeRequest(consumer="discovery", topics=("funding",), eligibility_policy=policy)
        assert request.eligibility_policy == policy
