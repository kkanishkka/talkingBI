"""
app/services/insight_narration_agent.py
══════════════════════════════════════════════════════════════════════
Agent 6: Insight Narrator

Generates tiered, grounded, business-language insights from the
ExecutionResult and QueryIntent.

Insight tiers (always in this order):
  1. Direct answer — "Retired customers have the highest rate at 25.1%"
  2. Comparative   — "3.2× the dataset average of 7.8%"
  3. Diagnostic    — "Despite high rate, retired is only 4.2% of volume"
  4. Prescriptive  — "Target retired + student segments for max ROI"
  5. Caveat        — assumptions exposed if LLM unavailable

All numbers come from execution result rows, never from schema alone.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.llm_client import llm_client
from app.core.models import (
    AssumptionBlock, ExecutionResult, InsightReport,
    MetricType, QueryIntent,
)

import logging
logger = logging.getLogger(__name__)


# ── LLM prompt ────────────────────────────────────────────────────

_NARRATOR_SYSTEM = """You are a senior business analyst generating dashboard insights.
Given the user's question, computed analysis results, and metric type,
output ONLY a valid JSON object:

{
  "headline": "one direct sentence answering the user's question with specific numbers",
  "bullets": [
    "bullet 1 — direct answer with numbers (e.g. 'Retired: 25.1%, highest in dataset')",
    "bullet 2 — comparative insight (e.g. '3.2× above the overall average of 7.8%')",
    "bullet 3 — diagnostic pattern (e.g. 'Small segment: 4.2% of total volume')",
    "bullet 4 — prescriptive recommendation starting with a verb"
  ],
  "so_what": "one actionable recommendation starting with a verb",
  "data_caveat": "any important assumption or data quality note, or null"
}

RULES:
- Headline must directly answer the user's question. Include the top value and number.
- Use **bold** around key values: **Retired**, **25.1%**
- For rate: express as percent (25.1% not 0.251)
- For count: use comma-formatted integers
- Mention the top performer AND the weakest for contrast
- Compute average/ratio from the data in your head if needed
- bullets must have exactly 3–4 items
- so_what must start with an action verb (Target, Prioritise, Investigate, Monitor, Review)
- Output ONLY valid JSON. No markdown. No extra keys.
"""


def _fmt(value: Any, metric: str) -> str:
    try:
        f = float(value)
        if metric == MetricType.rate:
            return f"{f * 100:.1f}%"
        if metric in (MetricType.count, MetricType.sum):
            return f"{int(f):,}"
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return str(value)


def _build_narrator_message(intent: QueryIntent, result: ExecutionResult) -> str:
    metric  = str(intent.metric)
    x       = result.x_field
    y       = result.y_field
    rows    = result.data[:15]

    lines = "\n".join(
        f"  {row.get(x, '?')}: {_fmt(row.get(y), metric)}"
        for row in rows
    )
    return (
        f"User question: {intent.raw_prompt}\n\n"
        f"Metric: {result.metric_label} (type: {metric})\n"
        f"Top results ({result.row_count} total):\n{lines}"
    )


# ── template fallback ─────────────────────────────────────────────

def _template_narrate(intent: QueryIntent, result: ExecutionResult) -> InsightReport:
    metric  = str(intent.metric)
    x       = result.x_field
    y       = result.y_field
    data    = result.data

    if not data:
        return InsightReport(
            headline="No data returned for this query.",
            bullets=["The analysis returned no results. Check your query and filters."],
            so_what="Review the dataset columns and try a broader query.",
        )

    vals = []
    for row in data:
        try:
            vals.append(float(row[y]))
        except (TypeError, ValueError, KeyError):
            pass

    if not vals:
        return InsightReport(
            headline=f"{result.result_label} — values could not be parsed.",
            bullets=["Verify the metric column contains numeric data."],
            so_what="Check the dataset for data type issues.",
        )

    avg         = sum(vals) / len(vals)
    top_row     = data[0]
    bottom_row  = data[-1]
    top_x       = str(top_row.get(x, "Unknown"))
    top_y       = _fmt(top_row.get(y), metric)
    bot_x       = str(bottom_row.get(x, "Unknown"))
    bot_y       = _fmt(bottom_row.get(y), metric)
    avg_fmt     = _fmt(avg, metric)

    try:
        ratio = float(top_row.get(y, 0)) / max(float(bottom_row.get(y, 1)), 1e-9)
        ratio_str = f"{ratio:.1f}×"
    except (ZeroDivisionError, TypeError, ValueError):
        ratio_str = "significantly"

    qtype = str(intent.question_type)
    verb_map = {
        "ranking": "Prioritise", "comparison": "Focus on",
        "distribution": "Investigate", "trend": "Monitor",
        "aggregation": "Track", "correlation": "Leverage",
    }
    verb = verb_map.get(qtype, "Investigate")

    bullets = [
        f"**{top_x}** leads at {top_y} — the highest {result.metric_label.lower()} in the dataset.",
        f"**{bot_x}** is the weakest at {bot_y}, compared to the average of {avg_fmt} across all categories.",
        f"The spread between top and bottom is **{ratio_str}** — a substantial gap worth investigating.",
    ]
    if metric == MetricType.rate and len(data) >= 3:
        mid  = data[len(data) // 2]
        mid_x = str(mid.get(x, ""))
        mid_y = _fmt(mid.get(y), metric)
        bullets.append(
            f"Mid-tier: **{mid_x}** at {mid_y}. "
            f"Focus on top performers to maximise conversion efficiency."
        )

    return InsightReport(
        headline=f"**{top_x}** shows the highest {result.metric_label.lower()} at {top_y}.",
        bullets=bullets,
        so_what=(
            f"{verb} **{top_x}** and similar high-performing categories "
            f"to leverage the {ratio_str} advantage over the weakest segment."
        ),
        data_caveat=None,
    )


# ── assumption block builder ──────────────────────────────────────

def build_assumption_block(
    intent:       QueryIntent,
    plan_formula: str,
) -> AssumptionBlock:
    metric_assumption = ""
    if intent.metric == MetricType.rate and intent.target_variable:
        pclass = intent.rate_value or "yes"
        metric_assumption = (
            f"Rate computed as: proportion of rows where "
            f"'{intent.target_variable}' = '{pclass}' within each group."
        )
    elif intent.metric == MetricType.count:
        metric_assumption = "Count = number of rows in each group."
    elif intent.target_variable:
        metric_assumption = (
            f"{intent.metric.title()} computed on column '{intent.target_variable}'."
        )

    dim_assumption = ""
    if intent.primary_dimension:
        dim_assumption = f"Grouped by: '{intent.primary_dimension}'"
        if intent.secondary_dimension:
            dim_assumption += f" and '{intent.secondary_dimension}'"
        dim_assumption += "."

    filter_assumptions = [
        f"Filter applied: {f.column} {f.operator} {f.value}"
        for f in intent.filters
    ]

    return AssumptionBlock(
        metric_assumption=    metric_assumption,
        dimension_assumption= dim_assumption,
        filter_assumptions=   filter_assumptions,
        formula_spec=         plan_formula,
        positive_class=       intent.rate_value,
        can_correct=          True,
    )


# ── public API ────────────────────────────────────────────────────

def narrate_insights(
    intent:  QueryIntent,
    result:  ExecutionResult,
    viz_spec: Any,  # VizSpec — passed for context, not always needed
) -> InsightReport:
    """
    Generate InsightReport from computed result.
    Primary: LLM. Fallback: template.
    """
    if not result.success or not result.data:
        return InsightReport(
            headline="No data available for this query.",
            bullets=["The analysis returned no results."],
            so_what="Try broadening your query or checking your filters.",
        )

    if llm_client.available:
        msg = _build_narrator_message(intent, result)
        data = llm_client.complete_json(_NARRATOR_SYSTEM, msg, temperature=0.3)
        if data:
            try:
                bullets = data.get("bullets", [])
                if isinstance(bullets, str):
                    bullets = [bullets]
                return InsightReport(
                    headline=    data.get("headline", ""),
                    bullets=     bullets,
                    so_what=     data.get("so_what", ""),
                    data_caveat= data.get("data_caveat"),
                )
            except Exception as exc:
                logger.warning("InsightNarrator: LLM parse failed: %s", exc)

    logger.info("InsightNarrator: using template fallback")
    return _template_narrate(intent, result)