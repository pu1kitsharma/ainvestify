# Product quality review — 25 September 2026

**Verdict: reject the current results as a useful research product.** This is a
read-only review of deployed model outputs, prompted by the user's report that
the results are vague, confusing and unsupported. Mechanical completion of nine
sections and passing software tests did not establish usefulness. This document
is evaluation material, never a production answer or company template.

## Reported agrotech search

Run: `source_run_25b0f737e2a4`, thesis `agrotech`.

- Local `qwen3.5:9b`, five calls, 83.549 seconds, status `partial`.
- DuckDuckGo returned HTTP 202. Mwmbl returned three links across two searches:
  an unrelated company news topic, a closed-company Wikipedia page, and a
  precision-agriculture software directory.
- The model selected the directory. The runtime's `Extraction` schema explicitly
  allows only **one company per page**; the extraction prompt repeats this limit.
  This is an implementation restriction, not evidence that only one company fits.
- CropX was retained from the directory and assessed before its official website
  was established. Four evidence records refer to the same 587-character passage;
  these are not four independent findings. The passage also contains the end of
  a different company's listing.
- The model followed the directory profile, then proposed an official URL absent
  from supplied observed links. Source binding correctly rejected that URL. The
  run then ended without resolving identity or broadening the shortlist.
- The visible card says “cloud-based platform processes information gathered
  from soil sensors.” The assessment recommends a discussion while admitting
  that operational status and commercial evidence are unresolved. It does not
  supply a useful comparison or a company-specific reason to engage.
- Browser inspection confirmed exactly one company and limited source coverage.
  Discovery remains local; the Pro integration covers public-evidence preparation.

## Current drafts

GoCardless job `automation_8ce0f699c07e` is mechanically completed. Its records
cover a homepage, pricing and an old scale/funding blog. The source collector reads
the known website and an observed pricing link, at most two pages. It has no
current-status research step and its version-3 cache has no freshness expiry.

An official [Mollie announcement](https://www.mollie.com/news/mollie-and-gocardless)
dated 1 September 2026 says the acquisition of GoCardless was completed. The draft
misses this material ownership change. Its implication for a founder-focused
investment-preparation approach must be assessed; acquisition does not by itself
prove that all potential advisory work is unsuitable.

The user ran another preparation while this review was underway. Latest observed
CropX job: `automation_2f14aee105ce`, started 24 September 18:38:38 UTC and completed
18:40:27 UTC, using Claude Pro. It still cites only `S1`, the directory excerpt.
Its action asks to apply fixed charges, percentage components, caps and discounts
despite the source not establishing any charging model. Its founder opening
centres on a directory rating and asks about customer counts and renewals. This
is not a compelling basis for an approach. References to subscription product
lines also outrun the established business-model evidence.

CropX's [official about page](https://cropx.com/about-us/) describes growers and
agribusiness customers and an acquisition history. This readily available primary
source was not in the draft's evidence. A missing official website causes
`collect_preparation_evidence` to return immediately, leaving the weak directory
passage as the sole basis for a full preparation pack.

Both packs emphasise billing reconciliation and margins. The generation and
review prompts repeatedly describe these financial methods. This is a likely
contributor to their sameness, alongside sparse source evidence; it is an
inference, not a measured causal experiment.

## Required correction order

1. Discovery: gather enough relevant sources for a comparative shortlist; remove
   the one-company-per-directory constraint; resolve official identity through
   observed sources; use a bounded model-planned refinement when results are thin.
   Never manufacture companies to meet a count.
2. Research: model-select and collect primary evidence about product, customer,
   commercial activity, current ownership/status and recent developments. Record
   publication and retrieval dates and unresolved conflicts. A homepage and pricing
   page are not a full research pass. Separate research freshness from draft reuse.
3. Synthesis: answer why this company is interesting, what is supported, what is
   only hypothesised, and what specific work would help. Do not turn missing public
   research into an immediate demand for private ledgers or a standard fee audit.
4. Acceptance: independently assess factual currency, attribution, relevance,
   clarity and practical value. A valid schema, citations and a model reviewer
   saying “pass” are necessary engineering checks, not sufficient product quality.
   Evaluate fresh companies against these criteria before claiming recovery.

No company answers, database records or production prompts were changed during
this audit. No new inference, retry, benchmark or service restart was initiated.
Both observed preparation jobs were completed and no active search jobs were
present at the final read. Historical failures and original responses are retained.
