"""Live CC0 dataset -> company workspace -> local draft pack; temporary DB only."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.datasets import discover_dataset_companies
from agents.operating_workflow import prepare_operating_drafts, reconcile_workspace
from schemas import SourcedLead, WebSourcingRun
from store import Store

with tempfile.TemporaryDirectory(prefix="operations-smoke-") as folder:
    with Store(Path(folder) / "smoke.db") as store:
        run = WebSourcingRun(tenant_id="smoke", thesis="Hotel operators in India", geography="India", model="local")
        profiles = discover_dataset_companies(store, run)
        print(json.dumps({"dataset_companies": [p.name for p in profiles], "sources": [s.model_dump() for s in run.sources]}, indent=2), flush=True)
        if not profiles:
            sys.exit(1)
        profile = profiles[0]
        store.save_company(profile)
        lead = SourcedLead(tenant_id="smoke", company_id=profile.id, company_name=profile.name, company_profile=profile)
        store.save_lead(lead)
        reconcile_workspace(store, lead, geography="India", thesis="Assess whether operational and fundraising support would be useful; do not assume startup stage.")
        result = prepare_operating_drafts(store, lead)
        print(json.dumps({"company": profile.name, "draft_status": result.draft_status, "model": result.model,
                          "drafts": [d.model_dump() for d in result.drafts],
                          "work": [t.model_dump() for t in result.work_items], "capabilities": result.capabilities}, indent=2), flush=True)
