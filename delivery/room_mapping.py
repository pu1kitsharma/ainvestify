"""Read-only L0 reconciliation plan. Never guess ownership or merge histories."""
from __future__ import annotations

from collections import Counter
from typing import Literal, Optional

from delivery.contracts import Contract, Identifier
from schemas import Deal, SourcedLead
from workflow_schemas import OperatingWorkspace


class RoomMapping(Contract):
    workspace_id: Optional[str] = None
    lead_id: Optional[str] = None
    deal_id: Optional[str] = None
    state: Literal["unlinked", "link_candidate", "conflict", "explicit_migration_required"]
    reason: Identifier


def plan_room_mapping(
    tenant_id: str,
    workspaces: list[OperatingWorkspace],
    leads: list[SourcedLead],
    deals: list[Deal],
) -> tuple[RoomMapping, ...]:
    """Use a complete tenant snapshot; candidates are not authorization to write.

    Direct-entry leads use the same relation as discovered leads. This planner
    never creates leads/profiles or invents AI discovery provenance. Unknown deal
    references fail closed without disclosing whether another tenant owns them.
    """
    if not tenant_id or any(r.tenant_id != tenant_id for r in [*workspaces, *leads, *deals]):
        raise ValueError("Mapping requires one tenant-scoped snapshot")
    for records in (workspaces, leads, deals):
        if len({r.id for r in records}) != len(records):
            raise ValueError("Duplicate record IDs in mapping snapshot")
    lead_by_id = {r.id: r for r in leads}
    deal_ids = {r.id for r in deals}
    workspace_counts = Counter(w.lead_id for w in workspaces)
    promoted_counts = Counter(l.promoted_deal_id for l in leads if l.promoted_deal_id)
    result = []
    for workspace in sorted(workspaces, key=lambda w: w.id):
        lead = lead_by_id.get(workspace.lead_id)
        state, reason, deal_id = "unlinked", "unpromoted_lead", None
        if workspace_counts[workspace.lead_id] != 1:
            state, reason = "conflict", "duplicate_workspaces_for_lead"
        elif lead is None:
            state, reason = "conflict", "missing_lead"
        elif ((lead.company_id and lead.company_id != workspace.company_id)
                or (lead.company_profile and (lead.company_profile.tenant_id != tenant_id
                    or lead.company_profile.id != workspace.company_id))):
            state, reason = "conflict", "company_identity_mismatch"
        elif lead.promoted_deal_id:
            deal_id = lead.promoted_deal_id
            if deal_id not in deal_ids:
                state, reason = "conflict", "deal_unavailable_in_tenant"
            elif promoted_counts[deal_id] != 1:
                state, reason = "conflict", "ambiguous_promoted_deal"
            else:
                state, reason = "link_candidate", "unambiguous_promoted_deal"
        result.append(RoomMapping(workspace_id=workspace.id, lead_id=workspace.lead_id,
            deal_id=deal_id, state=state, reason=reason))
    candidate_ids = {r.deal_id for r in result if r.state == "link_candidate"}
    for deal in sorted(deals, key=lambda d: d.id):
        if deal.id not in candidate_ids:
            result.append(RoomMapping(deal_id=deal.id, state="explicit_migration_required",
                reason="no_unambiguous_workspace"))
    return tuple(result)
