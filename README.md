# ainvestify

An AI-driven, multi-agent system for sourcing and incubating early-stage tech companies, then helping them raise institutional funding — the way a boutique investment bank packages a raise, not a fund screening deals for its own book.

**Lifecycle:** source candidate companies → a human reviews and promotes a lead into an actual deal → sign an engagement mandate → ingest the company's own documents → extract structured metrics with mandatory citations → human review → external research corroboration → compile a cited, reviewable document suite (Teaser / CIM / Pro-forma) → track investor interest (demand book).

This system supports that process with cited data and a reviewable memo — it does not itself contact investors, negotiate terms, or run the raise. That stays a human-led relationship/advisory activity.

## Status

**Phase 0** — local, CPU-only validation, zero cloud spend. See `CLAUDE.md` and `deal_automation_architecture.md` for full project context, architecture, and the current list of open gaps.

## Setup

1. Install [Ollama](https://ollama.com/download) and confirm `ollama serve` is running.
2. `pip install -r requirements.txt` (or see the imports across `agents/*.py`, `schemas.py`, `store.py`, `main.py` for the current dependency set).
3. `python3 main.py "<what you want to do>"` — e.g. `"find promising fintech companies to incubate"` or `"screen this deal, I have the pitch deck ready"`.

## Read first

- `CLAUDE.md` — project context, locked-in decisions, conventions, and a running log of what's been built and validated.
- `deal_automation_architecture.md` — the full design doc: agent flow, data model, guardrails, model/infra tiering, zero-budget data stack, roadmap.
