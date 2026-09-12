"""
Prompt/directive endpoints (plan §2/§3, milestone 3).

`POST /api/prompt/classify` is the API-native equivalent of main.py's
top-level router. `POST /api/deals/{id}/directive/preview` is the API-native
equivalent of _confirm_with_human's first half: it classifies a free-text
directive into a proposed action and reasoning, but stops there -- it never
executes anything, so the frontend can render it as an inline confirm card
and let the human accept or override before anything happens, the same
non-negotiable gate _confirm_with_human enforces for the CLI.

There is deliberately no generic "/directive/execute" endpoint here. Milestone
1 flagged this as an open design question (see agents/planner_agent.py's
handle_directive dispatch, which was deliberately left un-refactored into a
generic dispatcher). Having now designed the real request/response shapes for
each action (mandate, ingest, extract, review decisions, research, compile,
teaser, pro-forma, investors), a single generic executor turns out not to be
the right shape: each action needs different parameters, and two of the
CLI's actions ("review", "review_research") aren't single-shot calls at all --
they're a whole review screen's worth of per-field decisions. So the concrete
per-action endpoints across deals.py/review.py/research.py/leads.py *are*
the execute side; the frontend maps a previewed action name to the matching
endpoint itself, the same role handle_directive's if/elif plays for the CLI.
"""
from fastapi import APIRouter, Depends, HTTPException

from agents.planner_agent import CONTINUE_WORDS, DEFAULT_ACTION, PlannerDecision, classify_directive
from api.deps import get_store, get_tenant_id
from api.models import DirectiveRequest, PromptRequest
from main import RouterDecision, classify_prompt
from store import Store

router = APIRouter(prefix="/api", tags=["prompt"])


@router.post("/prompt/classify", response_model=RouterDecision)
def classify(body: PromptRequest):
    return classify_prompt(body.prompt)


@router.post("/deals/{deal_id}/directive/preview", response_model=PlannerDecision)
def preview_directive(
    deal_id: str,
    body: DirectiveRequest,
    store: Store = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
):
    deal = store.get_deal(tenant_id, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")

    if body.directive.strip().lower() in CONTINUE_WORDS:
        return PlannerDecision(
            action=DEFAULT_ACTION[deal.status],
            reasoning="Plain continue -- using the deterministic next step for this state.",
        )
    return classify_directive(deal, body.directive)
