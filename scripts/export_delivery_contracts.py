"""Emit the L0 policy and schemas to stdout; no DB, model or network access.

Run: python3 scripts/export_delivery_contracts.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery.contracts import POLICY, ArtifactManifest, CheckResult, ReviewDecision
from delivery.room_mapping import RoomMapping
from delivery.workflow_contracts import DealRoomActivated, PublicEvidenceBundle, PublicKnowledgeRequest


if __name__ == "__main__":
    print(json.dumps({"policy": POLICY.model_dump(mode="json"), "schemas": {
        cls.__name__: cls.model_json_schema()
        for cls in (ArtifactManifest, CheckResult, ReviewDecision, RoomMapping,
            DealRoomActivated, PublicEvidenceBundle, PublicKnowledgeRequest)
    }}, indent=2, sort_keys=True))
