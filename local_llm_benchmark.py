#!/usr/bin/env python3
"""
local_llm_benchmark.py

Zero-cost, zero-cloud benchmark for candidate local LLMs on CPU-only hardware.
Measures real tokens/sec on YOUR machine instead of relying on published
benchmarks from someone else's CPU (see architecture doc, section 14).

Requirements (all free, open-source, no API keys, no GPU needed):
    1. Install Ollama:  https://ollama.com/download
    2. Start it:        ollama serve   (often starts automatically after install)
    3. pip install ollama

Usage:
    python local_llm_benchmark.py
    python local_llm_benchmark.py --models llama3.2:1b llama3.2:3b phi4-mini qwen2.5:7b
    python local_llm_benchmark.py --runs 5
"""

import argparse
import statistics
import sys
import time

try:
    import ollama
except ImportError:
    print("Missing dependency. Run: pip install ollama")
    sys.exit(1)

# A representative "structured extraction" style prompt: a short synthetic
# financial fact sheet plus an instruction to pull fields into JSON. This
# mirrors what the Structured Extraction Agent (architecture doc, section 5.3)
# will actually be asked to do, so throughput here is a far better signal
# than a generic chit-chat benchmark would be.
SAMPLE_DOCUMENT = """
Acme Robotics Inc. -- Series A Fact Sheet (FY2025)

Annual Recurring Revenue (ARR): $2,400,000, up from $1,050,000 the prior year.
Monthly Burn: $180,000. Cash on hand: $3,200,000. Runway: approximately 17.8 months.
Headcount: 34 full-time employees, up from 21 a year ago.
Cap table: Founders 58%, Seed investors 22%, Series A lead (Northbrook Ventures) 15%,
ESOP pool 5%.
Prior funding: Seed round of $1,500,000 closed March 2023, led by Founders Fund Angels.
"""

EXTRACTION_PROMPT = f"""Extract the following fields from the document below as strict JSON.
If a field is not present, use null. Do not guess or infer values that are not stated.

Fields: arr, arr_prior_year, monthly_burn, cash_on_hand, runway_months, headcount,
headcount_prior_year, cap_table (list of {{holder, pct}}), last_round_amount, last_round_lead.

Document:
{SAMPLE_DOCUMENT}

Return only the JSON object, no commentary."""

DEFAULT_MODELS = [
    "llama3.2:1b",   # candidate: Planner / Router agent
    "llama3.2:3b",   # candidate: Planner / Router agent (higher quality)
    "phi4-mini",      # candidate: Structured Extraction agent (native JSON/function-calling)
    "qwen2.5:7b",     # candidate: Market Research synthesis / Compilation stand-in
]


def ensure_model(model: str) -> bool:
    """Pull the model if it isn't already present locally. Returns False on failure."""
    try:
        local_models = {m.get("model", "") for m in ollama.list().get("models", [])}
    except Exception as e:
        print(f"  Could not reach local Ollama server ({e}). Is `ollama serve` running?")
        return False

    if model in local_models or any(model in m for m in local_models):
        return True

    print(f"  Pulling {model} (one-time download, size varies by model)...")
    try:
        ollama.pull(model)
        return True
    except Exception as e:
        print(f"  Failed to pull {model}: {e}")
        return False


def benchmark_model(model: str, runs: int):
    samples = []
    for i in range(runs):
        try:
            t0 = time.perf_counter()
            resp = ollama.generate(model=model, prompt=EXTRACTION_PROMPT, options={"temperature": 0})
            wall_s = time.perf_counter() - t0
        except Exception as e:
            print(f"  Run {i + 1} failed: {e}")
            continue

        eval_count = resp.get("eval_count", 0)
        eval_duration_ns = resp.get("eval_duration", 0)
        load_duration_ns = resp.get("load_duration", 0)

        tok_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns else 0.0
        samples.append({
            "wall_s": wall_s,
            "tok_per_sec": tok_per_sec,
            "eval_count": eval_count,
            "load_s": load_duration_ns / 1e9,
        })
        print(f"  run {i + 1}/{runs}: {tok_per_sec:.1f} tok/s, {eval_count} tokens, "
              f"{wall_s:.1f}s wall time (incl. {load_duration_ns / 1e9:.1f}s model load)")

    if not samples:
        return None

    # Drop the first run's cold-load time from the "steady state" figure where
    # possible -- model load is a one-time cost, not a per-call cost once a
    # real pipeline keeps the model warm.
    steady = samples[1:] if len(samples) > 1 else samples
    return {
        "model": model,
        "median_tok_per_sec": statistics.median(s["tok_per_sec"] for s in steady),
        "median_wall_s": statistics.median(s["wall_s"] for s in steady),
        "first_call_wall_s": samples[0]["wall_s"],
        "runs": len(samples),
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark local LLMs on this machine (CPU-only friendly).")
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS,
                         help="Ollama model tags to benchmark.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per model (first run includes model load time).")
    args = parser.parse_args()

    results = []
    for model in args.models:
        print(f"\n=== {model} ===")
        if not ensure_model(model):
            continue
        result = benchmark_model(model, args.runs)
        if result:
            results.append(result)

    if not results:
        print("\nNo successful runs. Check that `ollama serve` is running and that models pulled correctly.")
        sys.exit(1)

    results.sort(key=lambda r: -r["median_tok_per_sec"])

    print("\n" + "=" * 72)
    print(f"{'Model':<16} {'Median tok/s':>14} {'Median wall (s)':>16} {'Runs':>6}")
    print("-" * 72)
    for r in results:
        print(f"{r['model']:<16} {r['median_tok_per_sec']:>14.1f} {r['median_wall_s']:>16.1f} {r['runs']:>6}")

    print("\nSuggested mapping onto the architecture doc's agent roles (adjust once you see YOUR numbers,")
    print("not the ballpark figures cited in section 14 of the architecture doc):")
    print("  Planner / Router agent               -> fastest small model above (target: 30+ tok/s for a")
    print("                                           conversational loop that doesn't feel sluggish)")
    print("  Structured Extraction agent           -> the phi4-mini / gemma-class result -- read the raw")
    print("                                           JSON it produced for the sample prompt above and check")
    print("                                           it against the source numbers by hand, don't pick on")
    print("                                           speed alone")
    print(f"  Market Research / Compilation stand-in -> the largest model that completed all {args.runs} runs")
    print("                                           without the wall time becoming unusable for your workflow")
    print("\nSpeed is necessary but not sufficient -- the real decision criterion is whether each model's JSON")
    print("output for the extraction prompt above exactly matches the numbers actually stated in the sample")
    print("document. A fast model that fabricates a field is worse than a slow one that correctly returns null.")


if __name__ == "__main__":
    main()
