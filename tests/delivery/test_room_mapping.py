import pytest

from delivery.room_mapping import plan_room_mapping
from schemas import CompanyProfile, Deal, SourcedLead
from workflow_schemas import OperatingWorkspace


def records(promoted=False, manual=False):
    profile = CompanyProfile(id="company", tenant_id="owner", name="Synthetic company",
        website="https://synthetic.example", provenance={"origin": "manual"} if manual else {})
    lead = SourcedLead(id="lead", tenant_id="owner", company_name=profile.name,
        company_id=profile.id, company_profile=profile, promoted_deal_id="deal" if promoted else None)
    workspace = OperatingWorkspace(id="room", tenant_id="owner", lead_id=lead.id,
        company_id=profile.id, company_name=profile.name)
    deal = Deal(id="deal", tenant_id="owner", name=profile.name)
    return workspace, lead, deal


def test_unpromoted_lead_remains_unlinked():
    room, lead, _ = records()
    assert plan_room_mapping("owner", [room], [lead], [])[0].state == "unlinked"


def test_promoted_relation_is_candidate_without_mutation():
    room, lead, deal = records(promoted=True)
    before = [r.model_dump_json() for r in (room, lead, deal)]
    plan = plan_room_mapping("owner", [room], [lead], [deal])
    assert len(plan) == 1
    assert plan[0].state == "link_candidate"
    assert plan[0].deal_id == deal.id
    assert before == [r.model_dump_json() for r in (room, lead, deal)]


def test_legacy_deal_requires_explicit_migration():
    _, _, deal = records()
    assert plan_room_mapping("owner", [], [], [deal])[0].state == "explicit_migration_required"


def test_manual_entry_preserves_origin():
    room, lead, _ = records(manual=True)
    assert plan_room_mapping("owner", [room], [lead], [])[0].state == "unlinked"
    assert lead.company_profile.provenance == {"origin": "manual"}
    assert lead.discovery_signals == []


def test_ambiguous_promoted_links_never_merge():
    room, lead, deal = records(promoted=True)
    other = lead.model_copy(update={"id": "other-lead"})
    plan = plan_room_mapping("owner", [room], [lead, other], [deal])
    assert plan[0].reason == "ambiguous_promoted_deal"
    assert all(r.state != "link_candidate" for r in plan)


def test_duplicate_workspaces_are_conflicts():
    room, lead, deal = records(promoted=True)
    other = room.model_copy(update={"id": "other-room"})
    plan = plan_room_mapping("owner", [room, other], [lead], [deal])
    assert all(r.state == "conflict" for r in plan if r.workspace_id)


def test_wrong_company_or_missing_lead_is_not_backfilled():
    room, lead, deal = records(promoted=True)
    wrong = room.model_copy(update={"company_id": "another-company"})
    assert plan_room_mapping("owner", [wrong], [lead], [deal])[0].reason == "company_identity_mismatch"
    assert plan_room_mapping("owner", [room], [], [deal])[0].reason == "missing_lead"


def test_cross_tenant_snapshot_rejected_and_unknown_deal_is_opaque():
    room, lead, deal = records(promoted=True)
    with pytest.raises(ValueError, match="tenant-scoped"):
        plan_room_mapping("owner", [room], [lead], [deal.model_copy(update={"tenant_id": "other"})])
    assert plan_room_mapping("owner", [room], [lead], [])[0].reason == "deal_unavailable_in_tenant"


def test_nested_profile_tenant_must_match():
    room, lead, deal = records(promoted=True)
    lead.company_profile.tenant_id = "other"
    assert plan_room_mapping("owner", [room], [lead], [deal])[0].state == "conflict"


def test_duplicate_input_ids_rejected():
    room, lead, deal = records(promoted=True)
    with pytest.raises(ValueError, match="Duplicate"):
        plan_room_mapping("owner", [room], [lead, lead], [deal])
