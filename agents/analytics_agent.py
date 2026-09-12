"""
Analytics / Visualization Agent — architecture doc §5.6.

Deterministic, not generative: every chart is rendered by code (matplotlib)
against already-*approved* fields. There is no LLM call in this module --
numbers never pass through a free-text generation step here, only through
code that reads the already-validated ExtractionResult.

Charts are skipped, not stubbed, when their required fields aren't in an
approved/edited state -- e.g. no cap table pie chart if cap_table wasn't
extractable or wasn't approved (§5.6's own example).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from schemas import ChartArtifact, ExtractionResult, FieldStatus

APPROVED = (FieldStatus.APPROVED, FieldStatus.EDITED)


def _arr_growth_chart(result: ExtractionResult, out_dir: Path) -> ChartArtifact | None:
    if result.arr.status not in APPROVED or result.arr_prior_year.status not in APPROVED:
        return None
    if result.arr.value is None or result.arr_prior_year.value is None:
        return None

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar(["Prior Year", "Current Year"], [result.arr_prior_year.value, result.arr.value],
           color=["#94a3b8", "#2563eb"])
    ax.set_title("ARR: Prior Year vs. Current Year")
    ax.set_ylabel(f"ARR ({result.arr.unit})")
    for i, v in enumerate([result.arr_prior_year.value, result.arr.value]):
        ax.text(i, v, f"${v:,.0f}", ha="center", va="bottom", fontsize=9)

    path = out_dir / f"{result.deal_id}_arr_growth.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)

    return ChartArtifact(
        tenant_id=result.tenant_id, deal_id=result.deal_id,
        chart_type="arr_growth_bar",
        source_field_ids=["arr", "arr_prior_year"],
        storage_uri=str(path),
    )


def _cap_table_chart(result: ExtractionResult, out_dir: Path) -> ChartArtifact | None:
    if result.cap_table_status not in APPROVED or not result.cap_table:
        return None

    labels = [row.holder or "Unknown" for row in result.cap_table]
    sizes = [row.pct or 0 for row in result.cap_table]

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
    ax.set_title("Cap Table")

    path = out_dir / f"{result.deal_id}_cap_table.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)

    return ChartArtifact(
        tenant_id=result.tenant_id, deal_id=result.deal_id,
        chart_type="cap_table_pie",
        source_field_ids=["cap_table"],
        storage_uri=str(path),
    )


def generate_charts(result: ExtractionResult, out_dir: str) -> list[ChartArtifact]:
    """Pick and render whichever standard chart templates the *approved*
    data actually supports (§5.6) -- silently skipping the rest."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    charts = [
        _arr_growth_chart(result, out_path),
        _cap_table_chart(result, out_path),
    ]
    return [c for c in charts if c is not None]
