"""
app/services/coverage_engine.py
══════════════════════════════════════════════════════════════════════
KPI Coverage Calculator.

Was: computed and discarded.
Now: returns KPICoverage model, included in every DashboardResponse.

Coverage logic:
  - requested_kpis: from QueryIntent.requested_kpis
  - covered: KPIs whose keywords appear in any VizSpec title or formula_spec
  - uncovered: gaps the user should know about
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any

from app.core.models import KPICoverage


def compute_kpi_coverage(
    intent_kpis: list[str],
    viz_specs:   list[dict[str, Any]],  # list of VizSpec dicts
) -> KPICoverage:
    if not intent_kpis:
        return KPICoverage(
            requested_kpis=  [],
            covered_kpis=    [],
            uncovered_kpis=  [],
            coverage_pct=    100.0,
            coverage_note=   "No specific KPIs requested — full overview generated.",
        )

    covered:   list[str] = []
    uncovered: list[str] = []

    # collect all chart titles and formula_specs for matching
    chart_text = " ".join(
        (v.get("title", "") + " " + v.get("formula_spec", "")).lower()
        for v in viz_specs
    )

    for kpi in intent_kpis:
        # a KPI is "covered" if its key terms appear in the chart output
        kpi_words = set(kpi.lower().split())
        matched = any(word in chart_text for word in kpi_words if len(word) > 3)
        if matched:
            covered.append(kpi)
        else:
            uncovered.append(kpi)

    total = len(intent_kpis)
    pct   = round(len(covered) / total * 100, 1) if total > 0 else 100.0

    if pct == 100:
        note = "All requested KPIs are covered by the generated visualizations."
    elif pct >= 75:
        note = f"Most KPIs covered ({pct}%). Missing: {', '.join(uncovered)}."
    else:
        note = (
            f"Only {pct}% of KPIs covered. "
            f"Missing: {', '.join(uncovered)}. "
            f"Try a more specific query for uncovered KPIs."
        )

    return KPICoverage(
        requested_kpis= intent_kpis,
        covered_kpis=   covered,
        uncovered_kpis= uncovered,
        coverage_pct=   pct,
        coverage_note=  note,
    )