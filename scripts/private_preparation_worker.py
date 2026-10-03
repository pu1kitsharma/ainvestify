"""Run recorded model authoring against one room snapshot and local Ollama only."""
import json
from pathlib import Path
from agents.analysis.analyst_pack import prepare_analyst_pack
from agents.inference.local_models import AnalystModel
from agents.preparation.preparation_budget import PreparationBudget
from store import Store

job=Path.cwd()
request=json.loads((job/'request.json').read_text())
with Store(job/'snapshot.db') as store:
    lead=store.get_lead(request['tenant_id'],request['lead_id'])
    try:
        # Explicit installed local route: environment cannot select a hosted API.
        prepare_analyst_pack(store,lead,AnalystModel(request['model']),budget=PreparationBudget(110,max_calls=6,max_requests=6))
    except Exception as exc:
        (job/'failure.json').write_text(json.dumps({'error_type':type(exc).__name__}))
    workspace=store.get_workspace(request['tenant_id'],lead_id=request['lead_id'])
    (job/'result.json').write_text(json.dumps({'analyst_pack':workspace.analyst_pack,
        'analyst_pack_history':workspace.analyst_pack_history}))
