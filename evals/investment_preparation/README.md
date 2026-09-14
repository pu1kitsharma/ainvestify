# Investment preparation evaluation

For the subsequent multi-model router, actual thinking checks, model-specific
sampling and typed measurements, see [the routing update](model-routing.md).
The results below record the earlier implementation and remain historical.

The product's intended value is to turn sourced evidence into decisions and usable
work: a qualified company shortlist, a founder-specific offer, an underwriting
argument, commercial proof, financing materials and an investor process. A website
summary, document count or generated plan is not an investment outcome.

## What was researched and implemented

The versioned source registry and original paraphrased methods are in
`research_corpus/practice/methods.json`. It distinguishes:

| Practitioner role | Decision/work to learn | Primary references |
| --- | --- | --- |
| Investment banking / capital advisory | Establish the owner's objective, prepare for diligence, position the business, consider capital alternatives | [Morgan Stanley](https://advisor.morganstanley.com/liberty-wealth-management-group/documents/field/l/li/liberty-wealth-management-group/The_Anatomy_of_a_Deal_factsheet.pdf), [Houlihan Lokey](https://hl.com/services/corporate-finance/capital-solutions/) |
| Venture underwriting | Explain the customer problem, alternatives, business model and evidence behind the investment argument | [Sequoia](https://sequoiacap.com/article/writing-a-business-plan) |
| Acceleration / fundraising | Prepare proportional materials, cost the milestone, build and track an investor pipeline | [YC](https://www.ycombinator.com/blog/how-to-raise-a-seed-round), [Techstars](https://toolkit.techstars.com/build-your-investor-pipeline) |
| Incubation / E-cell | Develop an idea, team and prototype before assuming market readiness | [SINE](https://www.sineiitb.org/programs/nidhi-prayas/), [E-Cell IIT Bombay historical bootcamp](https://www.ecell.in/enbclub/bootcamp/) |
| Transaction documentation | Establish jurisdiction and transaction-specific requirements; keep documents internally consistent | [NVCA starting forms](https://nvca.org/model-legal-documents/), [SEBI regulatory reference](https://www.sebi.gov.in/legal/regulations/dec-2025/securities-and-exchange-board-of-india-merchant-bankers-regulations-1992-last-amended-on-december-5-2025-_98640.html) |

The analytical methods and example business tests are our synthesis. These firms
have not endorsed the product. A source's publication on a method does not prove
anything about a target company. An Indian private financing is not automatically
a US-form transaction or a public-issue merchant-banking mandate.

Methods are selected by workflow stage. The model still writes the company-specific
decisions, work, questions and responses. Methods and teaching examples enter the
instruction context separately from cited company records. They do not become
company evidence or fabricated search results.

Preparation v5 requires a decision question, next action and completion test for
each document. Research/brief v7 and preparation v5 get a separate model critique,
with bounded revision and retained failed attempts. Readiness priorities are
critiqued separately so later tasks cannot disappear behind a reasonable opening
task. After two attempts, a structurally valid, cited draft with unresolved model
review questions is retained as `needs_review`; other preparation documents
continue. Its questions remain visible in the workspace and downloads, and a
retry regenerates the flagged work. Invalid citations or malformed outputs still
fail validation. The critique is not independent verification or regulatory
approval, and `complete` means the preparation run finished, not investment
readiness or permission to send materials.

## Reproduce the response probes

```sh
PYTHONDONTWRITEBYTECODE=1 SOURCING_MODEL=phi4-mini python3 scripts/evaluate_preparation.py --output /tmp/phi-preparation.json
PYTHONDONTWRITEBYTECODE=1 SOURCING_MODEL=llama3.2:3b python3 scripts/evaluate_preparation.py --output /tmp/llama-preparation.json
PYTHONDONTWRITEBYTECODE=1 SOURCING_MODEL=phi4-mini python3 scripts/evaluate_preparation_review.py /tmp/preparation-critic.json
```

Six synthetic cases cover hospitality, prior-employer attribution, a pre-revenue
laboratory venture, founder outreach, transaction commissions and unverified growth.
Each model gets the same inputs and production output schemas, with and without
the practice/example context. These are first-response probes, not the full queued
workflow or its retries. No evaluation target/expected answer enters a prompt.
Generation uses the installed local Ollama model; it never writes a live workspace.

Initial recorded targeted-check results:

| Local model | Baseline first responses passing checks | With practice/examples |
| --- | ---: | ---: |
| phi4-mini | 1/6 | 4/6 |
| llama3.2:3b | 1/6 | 5/6 |
| qwen3:8b (candidate) | Not run | 6/6 |

**These are not investor-quality accuracy scores.** Many baseline failures were
length/schema failures. Inspection also found limitations in the checks:

- Phi's founder reply offered a useful company list/brief but failed a narrow
  keyword check expecting “shortlist”, “research”, “prospect” or “map”.
- Phi's laboratory plan passed the narrow checks while adding premature clinical
  and generic GTM work. This is a false positive for substantive usefulness.
- Llama avoided the clinical jump, but its record requests sometimes assumed an
  existing major customer or contract. Some economic reasoning remained generic.
- A critic returning an optional empty issues array missed both known bad drafts
  (`critic-results.json`). Requiring explained judgments caught the explicit
  funding/growth error but still ignored later readiness priorities
  (`critic-explained-results.json`). This prompted review of each priority.
- Qwen passed all six narrow probes, but still assumed subscription pricing in software examples and changed ambiguous supplier-payment wording into payments *from* suppliers. These are substantive limitations despite the pass count.
- The critic can incorrectly demand evidence for a question. Its verdicts require
  further calibration; none of these results warrants a claim of reliability.
- Per-priority review flagged the later generic GTM task and the funding/growth
  defect in the three development probes (`critic-item-results.json`). It still
  did not identify every questionable clinical recommendation and retained a
  false objection to requesting a revenue ledger. A case-level pass is not
  complete error coverage.

The first real-company shadow run also misread a mixed directory “Asks” passage:
a product sales offer was interpreted as a request for advisory help. Input
selection now isolates the explicit support-request span and preserves its source
ID. Maturity gets dated founding evidence separately. A second phi4-mini run
corrected the request but still returned an unhelpful broad clarification memo.
Neither shadow run was promoted to the live company. This prompted evaluation of
the stronger free local Qwen3 8B model rather than further claims about small-model
reliability. Candidate acceptance requires correct actor/request interpretation,
usable company-specific work, sourced assertions and no fabricated traction;
schema/keyword checks alone are insufficient.

Keep these raw results and limitations. Do not overwrite failures, turn keyword
pass rates into marketing metrics, or treat this development suite as a fresh
held-out benchmark after using its failures to change the implementation.

## Teaching data and actual fine-tuning

`teaching_examples.json` contains ten original synthetic examples: eight training
examples and two validation examples. It contains no client financial records or
copied source guides. It is authored seed data, not expert-reviewed gold data.
Selected training examples are used for in-context teaching; validation examples
and evaluation cases are excluded from prompt selection.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/export_preparation_training.py --output /tmp/preparation-training
```

The exporter validates output shape, citations and duplicate inputs across splits,
then writes chat-format `train.jsonl`, `valid.jsonl` and a provenance manifest.
The checked-in `training-seed` export is reproducible from the original examples.
It is not a trained model or a release dataset.

Actual local weight adaptation can use [MLX LoRA/QLoRA](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)
with a compatible checkpoint and these chat-file formats. No adapters, cloud
training or paid inference were created. A free [Qwen3 8B Q4 model](https://ollama.com/library/qwen3:8b)
was downloaded and is being evaluated locally (5.2 GB, Apache 2.0); downloading existing model weights
is not training them. The runtime does not automatically download models.
`PREPARATION_MODEL` selects the local model for substantive company preparation
without changing the fast discovery model selected by `SOURCING_MODEL`. Until
acceptance is established, preparation retains the existing configured model
(falling back to `phi4-mini`), rather than silently promoting the candidate.
Training on these ten examples alone would risk memorizing style while retaining
the reasoning failures above. A production training run needs substantially broader
reviewed examples, rights/consent tracking, company-disjoint splits and evaluation
against unseen business records before replacing an inference model.

## What counts as product value

Measure correctly qualified companies against the actual mandate, source-supported
claims, concrete work accepted without revision, unresolved investor questions,
time to a usable deliverable and manual corrections. Later measure actual founder
responses, qualified investor meetings, diligence issues resolved and funds received
from source records. Do not substitute generated task counts for those outcomes.

Public research cannot establish private cash, shareholder consent, real investor
interest or completed transactions. The current local product prepares internal
work; external outreach, execution, regulated sign-offs and receipt of capital are
not autonomous capabilities. The user has not authorized outbound messaging.

The real-company check also exposed an engagement-framing error: asking whether a startup needs an accelerator caused a model to reject a young company because it already had a clear product. Preparation v5 instead assesses useful initial research/preparation work, prohibits contradictory maturity claims and does not equate preparatory work with an investment decision. The first corrected Qwen run reached `proceed` against the explicit request; document quality is evaluated separately.

The subsequent real-company document **failed acceptance**. Its memo proposed
deducting cost savings and retention from elapsed time, mixing incompatible
quantities. Its completion test also imported unpaid balances and contribution
without connecting them to the stated question. The critic missed that defect
while raising other questionable objections. The isolated run was stopped after
this substantive failure; remaining products were not fully evaluated.
`qwen3-real-company-shadow.json` preserves the generated draft, reviewer responses
and this finding. Nothing from the shadow run was promoted into a live company,
and Qwen remains an optional candidate rather than the default. The existing
default's documented failures also remain unresolved; retaining it is not a
quality endorsement.

Implementation verification: 94 affected Python regression tests passed, frontend
build/lint passed, and browser checks covered the company dashboard, three-step
workspace, background/retry behavior, review questions, sources and mobile layout.
These are software checks, not proof of analytical reliability.
