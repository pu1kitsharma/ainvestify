# Task routing and reasoning evaluation

This extends the [earlier evaluation](README.md). The old non-thinking Qwen run
remains a recorded failure. The new path explicitly enables thinking using the
[Ollama thinking API](https://docs.ollama.com/capabilities/thinking), with separate
budgets and routing metadata. This does not change model weights.

## Runtime behavior

**Current resource-aware policy:** workers detect machine memory at startup.
Below 24 GB, defaults are Phi4-mini plus Qwen3:8b for analysis/review, a 12,288-token
context and a 4,096-token initial reasoning budget. The 14B defaults in the table
and explicit configuration example below apply to larger machines. Explicit
environment overrides still take precedence. Small preliminary candidate
classifications now use the fast route; evidence volume can escalate them.
See [the queue, source and review repair](discovery-and-preparation-repair.md)
for the observed 16 GB memory failure and latest validation results.

| Work | Default local route | Why |
| --- | --- | --- |
| Short extraction / simple request interpretation / short founder email | Phi4-mini, 2,200 output tokens | Low data volume and a narrow task |
| Highest-complexity inputs | Qwen3:14b with thinking | More evidence to reconcile; quality/latency weights control this escalation |
| Screening, research, suitability, diligence, commercial tests, financing and metric extraction | Qwen3:8b with thinking, 8,192 tokens | Analytical task; latency preference cannot downgrade it |
| Quality review | Qwen3:14b with thinking; separately configurable | Separate generation call; not independent verification |
| Validation retry | Reasoning route with a larger bounded budget | Repair an identified failure without blindly repeating a cheap call |

Requests are routed using trusted stage names, input size, evidence-record count,
retry status and quality/latency preferences. The complexity score is a transparent
heuristic, **not a learned or calibrated difficulty/accuracy estimate**. Instructions
inside scraped pages cannot alter the routing settings. Routes return to the fast
model for subsequent simple work; the previous model choice does not leak into it.
A review using the same model is not an independent opinion or a voting ensemble.

Configuration is read when a worker model is constructed:

```sh
SOURCING_MODEL=phi4-mini \
REASONING_MODEL=qwen3:8b \
REVIEW_MODEL=qwen3:14b \
ESCALATION_MODEL=qwen3:14b \
MODEL_QUALITY_WEIGHT=0.8 \
MODEL_LATENCY_WEIGHT=0.2 \
REASONING_MAX_TOKENS=8192 \
FAST_MAX_TOKENS=2200 \
MODEL_CONTEXT_TOKENS=16384 \
MODEL_TEMPERATURE=0 \
REASONING_TEMPERATURE=0.6 \
python3 scripts/serve_local.py
```

`PREPARATION_MODEL` overrides the fast preparation model only. Quality/latency
weights are normalized preferences for optional escalation, not neural-network
weights or claims about model quality. Nonnegative weights cannot both be zero.
Supported thinking-model families are Qwen3, DeepSeek R1 and GPT-OSS; only installed
local models are called. A missing model fails visibly rather than silently using
an unqualified cheaper model. No model is downloaded automatically. GPT-OSS uses
its documented thinking levels; Qwen3 uses the boolean switch.

Each generated product records the selected model, task, routing reason, settings,
actual elapsed time, token counts when supplied by Ollama, and finish reason.
Writer and reviewer metadata are recorded separately. The runtime also records whether Ollama actually returned a thinking field; requesting thinking is not enough. Thinking traces are not
stored in company records. An exhausted token budget is a failed response even if
its partial text happens to parse as JSON. Financial results still come from the
source-backed calculation code, not model-supplied arithmetic.

## Quantitative preparation

Work products can propose typed measurements: named operand records, dimensions,
units, operation and comparable cohort/window. Code rejects subtracting or
comparing different dimensions/units and dividing like dimensions expressed in
different units. Displayed measurement formulas are assembled from the validated
structure. No observed values or numerical results are fabricated. The proposed
records and relevance of a measurement still require evidence and substantive
review; dimensional validity alone cannot prove a sound investment argument.

A fifth review criterion explicitly examines quantitative logic. The original
failure is retained as a regression input. Unrelated-company financial examples
were removed from the three work-product prompts after their economic terminology
leaked into unrelated companies; practitioner methods remain available.

## Reproduce the live-model probes

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_reasoning_route.py \
  --input evals/investment_preparation/reasoning-regression-input.json \
  --output /tmp/reasoning-replay.json

PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_reasoning_route.py --fresh \
  --input evals/investment_preparation/reasoning-regression-input.json \
  --output /tmp/reasoning-fresh.json
```

These calls use local Ollama against the preserved public company evidence. They
never update a live company workspace. The original draft is used only in the
replay review. The fresh generation uses the production work instructions and
measurement schema, without anchoring on the old draft. Neither probe is a full
fundraise, a fresh held-out benchmark or an investor-quality accuracy score.

The first thinking-enabled replay caught the old time/retention error and
unrelated completion criteria, but its rewrite still implied that asking for
introductions proved demand and used ambiguous labor-cost subtraction. Its critic
passed that rewrite: another false positive, preserved in
`reasoning-route-results.json`. This prompted the typed measurements, removal of
unrelated financial examples and clearer separation of assistance requests from
buyer demand. A model's approval is never sufficient acceptance evidence.


Reasoning calls now omit Ollama's grammar-constrained `format` parameter and send
the output schema in the prompt instead. The final answer must still pass the
original Pydantic schema and all evidence/unit checks; malformed JSON is rejected.
This avoids the interaction documented in
[Ollama issue 10538](https://github.com/ollama/ollama/issues/10538). A local small
probe did return thinking with the old format path, so suppression is **not a
proven cause of all earlier failures on this machine**. Reasoning calls now fail
visibly if the runtime provides no thinking output, rather than labeling a flag
as proof of reasoning. Thinking text is neither logged nor displayed.


Qwen reasoning now uses its [author-recommended sampler](https://huggingface.co/Qwen/Qwen3-8B#best-practices):
temperature 0.6, top-p 0.95, top-k 20 and min-p 0. Qwen explicitly discourages
greedy decoding for thinking. The earlier temperature-zero unconstrained probe
was stopped after roughly five minutes without a completed first answer; its
report remains `reasoning-unconstrained-results.json`. This observation alone
does not prove an internal repetition loop. `REASONING_TEMPERATURE` is separate
from the fast route's `MODEL_TEMPERATURE` and must be positive. Token budgets remain
bounded for local resource limits; they are lower than the model card's maximum
benchmarking recommendations. Budget exhaustion remains a visible failed attempt.


`ESCALATION_MODEL` optionally changes the checkpoint for high input complexity or a validation retry (for
example from Qwen3 8B to 14B), in addition to increasing the reasoning budget.
It defaults to qwen3:14b and must already be installed; an explicitly empty setting retains the reasoning model.
The 14B free local checkpoint was downloaded for evaluation, not trained. It is
part of the default routing configuration. This is a model-selection policy, not an assertion of investor-quality accuracy.

The sampled 8B probe invented unsupported customer counts, percentages and fees.
Its final revision also failed the measurement record contract. These failures
are preserved in `reasoning-sampled-results.json`. Work-product version 7 now
requires each numeric assertion in its prose to be bound to an exact supporting
source quote before a model review runs. It rejects unsupported digits, fabricated
quotes and unattributed founder-history figures. Company-supplied records and
code-calculated figures use distinct source records; they are not public claims.
This literal support check cannot establish semantic entailment or external truth
and does not detect every fabricated statement expressed without digits.

## Real-evidence outcome

`reasoning-engagement-results.json` preserves a fresh 14B run using the actual
public evidence and the prior engagement decision, without changing live records.
Its first draft failed numeric grounding. Its revision removed unsupported
digits and correctly distinguished requests for introductions from buyer demand.
The three generation/review calls took 527 seconds in total with a 12,288-token
context and an initial 6,144-token output budget; all returned actual thinking.

**Substantive acceptance failed despite the automated `checked_draft` verdict.**
The revision asserted inventory accuracy and reduced effort without observed
comparisons. Its completion test depended on external outreach despite the next
action only preparing a proposal. The reviewer also turned unknown revenue into
“no revenue.” These are retained false positives, not investor-quality successes.
No generated draft from this evaluation was promoted into the live workspace.
The recorded automated status must not be interpreted as independent acceptance.

After this run, validation feedback was changed to name all affected numeric
fields and unused claims together; reviewers now receive capability and engagement
context and explicit instructions on these observed errors. These changes have
regression coverage but have not demonstrated elimination of semantic false
positives on a fresh held-out company. Routing and reasoning configuration are
implemented; reliable unattended investor-quality analysis is not established.
