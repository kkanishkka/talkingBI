"""
app/services/result_insight_engine.py
══════════════════════════════════════════════════════════════════════
Result-level Insight Engine — v2 (schema-agnostic)

v2 changes:
  ① Removed ALL hardcoded domain strings:
       "sales", "profit", "revenue" lookups for anomaly detection → GONE
     Replaced by:
       _find_paired_metrics() — finds metric pairs from the actual
         chart results, not from hard-coded column name patterns.
       _anomaly_insight_generic() — detects the high-primary/low-secondary
         pattern for ANY two metrics with the same dimension.

  ② _ranking_insight() is unchanged (already schema-agnostic).

  ③ _kpi_summary_insight() is unchanged.

  ④ _margin_anomaly() is a new generic detector:
       Given any two metrics (M1, M2) that share a dimension,
       finds rows where M1 is high and M2/M1 ratio is below a
       threshold — flags as "high X but low Y relative to X".
       Works for sales/profit, revenue/cost, los/cost, etc.

All numbers come from execution results — never from column metadata.

Public API (unchanged):
  generate_result_insights(plan, execution) → list[dict]
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.llm_client import llm_client
from app.services.multi_executor import ChartResult, KPIResult, MultiExecutionResult
from app.services.planner import DashboardPlan

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Formatting helpers
# ═══════════════════════════════════════════════════════════════════

def _fmt(value: Any, metric: str) -> str:
    try:
        f = float(value)
        if metric == "rate":
            return f"{f * 100:.1f}%"
        if metric == "count":
            return f"{int(f):,}"
        if abs(f) >= 1_000_000:
            return f"{f / 1_000_000:.2f}M"
        if abs(f) >= 1_000:
            return f"{f / 1_000:.1f}K"
        return f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(part: float, total: float) -> str:
    if total == 0:
        return "N/A"
    return f"{part / total * 100:.1f}%"


# ═══════════════════════════════════════════════════════════════════
# Per-chart insight — schema-agnostic ranking analysis
# ═══════════════════════════════════════════════════════════════════

def _ranking_insight(cr: ChartResult) -> Optional[dict]:
    """
    Top performer, bottom, spread, top-N concentration.
    Fully schema-agnostic: uses x_field and y_field from result,
    not hardcoded column names.
    """
    data = cr.execution_result.data
    if not data or len(data) < 2:
        return None

    sp     = cr.sub_plan
    metric = sp.metric
    x      = cr.execution_result.x_field or sp.dimension or ""
    y      = cr.execution_result.y_field or "value"

    vals = [(row.get(x, "?"), _safe_float(row.get(y))) for row in data]
    vals = [(xv, yv) for xv, yv in vals if yv is not None]
    if not vals:
        return None

    vals_sorted = sorted(vals, key=lambda t: t[1], reverse=True)
    top_x, top_y = vals_sorted[0]
    bot_x, bot_y = vals_sorted[-1]
    total = sum(v for _, v in vals)
    avg   = total / len(vals) if vals else 0

    obs = []
    obs.append(
        f"**{top_x}** leads with {_fmt(top_y, metric)} — "
        f"{_pct(top_y, total)} of total."
    )

    if bot_y is not None and bot_y < 0 and metric in ("sum", "mean"):
        obs.append(f"**{bot_x}** is negative: {_fmt(bot_y, metric)}.")
    elif bot_y is not None:
        ratio = top_y / max(abs(bot_y), 1e-9)
        obs.append(
            f"**{bot_x}** is the weakest at {_fmt(bot_y, metric)} "
            f"({ratio:.1f}× below the leader)."
        )

    if len(vals_sorted) >= 3 and total > 0:
        top3 = sum(v for _, v in vals_sorted[:3])
        obs.append(f"Top 3 contribute {_pct(top3, total)} of total.")

    below = sum(1 for _, v in vals if v < avg)
    if below > 0:
        obs.append(
            f"{below} of {len(vals)} segments are below average "
            f"({_fmt(avg, metric)})."
        )

    return {
        "title":           sp.label,
        "insight_text":    " ".join(obs),
        "category":        "ranking",
        "priority":        "high",
        "evidence_fields": [x, y],
        "confidence":      0.90,
    }


# ═══════════════════════════════════════════════════════════════════
# Generic cross-metric anomaly detection
# ═══════════════════════════════════════════════════════════════════

def _find_paired_metrics(charts: list[ChartResult]) -> list[tuple[ChartResult, ChartResult]]:
    """
    Find pairs of ChartResults that share the same dimension (x_field)
    but measure different metrics. These are candidates for cross-metric
    anomaly detection.

    Returns list of (primary_chart, secondary_chart) pairs.
    Works for any metric combination — not just sales/profit.
    """
    pairs = []
    for i, cr1 in enumerate(charts):
        for cr2 in charts[i+1:]:
            x1 = cr1.execution_result.x_field
            x2 = cr2.execution_result.x_field
            t1 = cr1.sub_plan.target
            t2 = cr2.sub_plan.target
            # Same dimension, different metric targets
            if x1 and x1 == x2 and t1 != t2:
                pairs.append((cr1, cr2))
    return pairs


def _margin_anomaly(cr1: ChartResult, cr2: ChartResult) -> Optional[dict]:
    """
    Generic cross-metric anomaly:
    Finds rows where metric1 is high but metric2/metric1 ratio is very low
    (or metric2 is negative).

    Examples this catches:
      - High sales, negative profit
      - High revenue, low margin
      - High LOS (length of stay), low cost_per_day
      - High order count, low average order value

    The insight text uses the actual column labels — never hardcoded terms.
    """
    x_field = cr1.execution_result.x_field or ""
    if not x_field or x_field != cr2.execution_result.x_field:
        return None

    map1 = {r.get(x_field): _safe_float(r.get("value")) for r in cr1.execution_result.data}
    map2 = {r.get(x_field): _safe_float(r.get("value")) for r in cr2.execution_result.data}

    shared = set(map1) & set(map2)
    if len(shared) < 2:
        return None

    label1 = cr1.sub_plan.label.split(" by ")[0]  # "Total Sales"
    label2 = cr2.sub_plan.label.split(" by ")[0]  # "Total Profit"
    dim_label = x_field.replace("_", " ").title()

    negatives = []
    low_ratio  = []

    for k in shared:
        v1 = map1[k]
        v2 = map2[k]
        if v1 is None or v2 is None:
            continue
        if v1 > 0 and v2 < 0:
            negatives.append((k, v1, v2))
        elif v1 > 0 and 0 <= v2 / v1 < 0.05:
            low_ratio.append((k, v1, v2))

    obs = []
    if negatives:
        names = ", ".join(f"**{n[0]}**" for n in negatives[:3])
        obs.append(
            f"Negative {label2} despite positive {label1} in: {names}. "
            f"Investigate cost or discount structure."
        )
    if low_ratio:
        names = ", ".join(f"**{n[0]}**" for n in low_ratio[:3])
        obs.append(f"Very low {label2}/{label1} ratio (<5%) in: {names}.")

    if not obs:
        return None

    return {
        "title":           f"⚠ {label1} vs {label2} Anomaly",
        "insight_text":    " ".join(obs),
        "category":        "anomaly",
        "priority":        "high",
        "evidence_fields": [x_field],
        "confidence":      0.88,
    }


# ═══════════════════════════════════════════════════════════════════
# KPI summary
# ═══════════════════════════════════════════════════════════════════

def _kpi_summary_insight(kpi_results: list[KPIResult]) -> Optional[dict]:
    if not kpi_results:
        return None
    parts = [f"**{k.definition.label}**: {k.formatted}" for k in kpi_results if k.success]
    if not parts:
        return None
    return {
        "title":           "Key Metrics Summary",
        "insight_text":    " | ".join(parts),
        "category":        "summary",
        "priority":        "high",
        "evidence_fields": [],
        "confidence":      0.99,
    }


# ═══════════════════════════════════════════════════════════════════
# LLM enrichment — schema-agnostic prompt
# ═══════════════════════════════════════════════════════════════════

_INSIGHT_SYSTEM = """\
You are a senior BI analyst. Given computed data results for an arbitrary dataset,
generate 2-3 sharp, actionable business insights.
Output ONLY valid JSON:
{
  "insights": [
    {
      "title": "short title",
      "insight_text": "one or two sentences with specific numbers from the data",
      "category": "ranking|anomaly|trend|opportunity|risk",
      "priority": "high|medium|low"
    }
  ]
}
Rules:
- Use ONLY the numbers provided — do not guess or hallucinate
- At least one insight must start with an action verb (Target, Investigate, Monitor, Review, Prioritise)
- Do not assume the domain — the data could be ecommerce, healthcare, finance, or any other domain
- Output ONLY valid JSON, no markdown
"""


def _llm_enrich(plan: DashboardPlan, execution: MultiExecutionResult) -> list[dict]:
    if not llm_client.available:
        return []

    lines = []
    for kr in execution.kpi_results:
        if kr.success:
            lines.append(f"KPI: {kr.definition.label} = {kr.formatted}")

    for cr in execution.successful_charts[:4]:
        top3 = cr.execution_result.data[:3]
        x = cr.execution_result.x_field or ""
        for row in top3:
            xv = row.get(x, "?")
            yv = row.get("value")
            lines.append(f"{cr.sub_plan.label}: {xv} = {yv}")

    if not lines:
        return []

    msg  = f"Query: {plan.query_summary}\n\nComputed data:\n" + "\n".join(lines)
    data = llm_client.complete_json(_INSIGHT_SYSTEM, msg, temperature=0.3)
    if not data:
        return []

    try:
        return [
            {
                "title":           i.get("title", ""),
                "insight_text":    i.get("insight_text", ""),
                "category":        i.get("category", "analysis"),
                "priority":        i.get("priority", "medium"),
                "evidence_fields": [],
                "confidence":      0.85,
            }
            for i in data.get("insights", [])
        ]
    except Exception as exc:
        logger.warning("result_insight_engine LLM parse: %s", exc)
        return []


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def generate_result_insights(
    plan:      DashboardPlan,
    execution: MultiExecutionResult,
) -> list[dict]:
    """
    Generate insights from actual computed values.
    Fully schema-agnostic — works for any domain/table.

    Returns a priority-sorted list of insight dicts (high → low).
    """
    insights: list[dict] = []

    # 1. KPI summary card
    kpi_summary = _kpi_summary_insight(execution.kpi_results)
    if kpi_summary:
        insights.append(kpi_summary)

    # 2. Per-chart ranking insights (schema-agnostic)
    for cr in execution.successful_charts:
        ins = _ranking_insight(cr)
        if ins:
            insights.append(ins)

    # 3. Cross-metric anomaly detection (generic — not sales/profit specific)
    pairs = _find_paired_metrics(execution.successful_charts)
    for cr1, cr2 in pairs[:3]:   # check up to 3 pairs
        anom = _margin_anomaly(cr1, cr2)
        if anom:
            insights.append(anom)

    # 4. Optional LLM enrichment (schema-agnostic prompt)
    llm_insights = _llm_enrich(plan, execution)
    insights.extend(llm_insights)

    # Sort: high → medium → low
    order = {"high": 0, "medium": 1, "low": 2}
    insights.sort(key=lambda i: order.get(i.get("priority", "low"), 3))

    return insights[:8]