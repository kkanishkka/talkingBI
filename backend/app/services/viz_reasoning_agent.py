"""
app/services/viz_reasoning_agent.py
════════════════════════════════════════════════════════════════════
Agent 5: Visualization Reasoner

Replaces: chart_recommender.py

Responsibility:
  Choose the right chart type based on ANALYTICAL INTENT, not just
  column types. This is the key difference from the old recommender.

  Decision framework:
  ┌─────────────────────────┬───────────────────────────────────┐
  │ Intent                  │ Chart                             │
  ├─────────────────────────┼───────────────────────────────────┤
  │ ranking (many cats)     │ horizontal_bar (sorted desc)      │
  │ ranking (few cats)      │ bar (sorted desc)                 │
  │ comparison (2 groups)   │ bar side-by-side                  │
  │ distribution (numeric)  │ histogram                         │
  │ distribution (categoric)│ pie (≤5) or bar (>5)             │
  │ trend over time         │ line                              │
  │ correlation 2 metrics   │ scatter                           │
  │ part-to-whole (≤6 cats) │ pie / donut                       │
  │ KPI / single metric     │ kpi_card                          │
  └─────────────────────────┴───────────────────────────────────┘

Usage:
  from app.services.viz_reasoning_agent import reason_visualization
  viz_spec = reason_visualization(query_intent, execution_result, schema_profile)
════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any


# ── chart selection logic ─────────────────────────────────────────

def _select_chart_type(
    question_type: str,
    metric: str,
    row_count: int,
    x_field: str | None,
    schema_profile: dict[str, Any],
) -> str:
    """
    Core decision: pick chart type from analytical intent.
    """
    # trend → always line
    if question_type == "trend":
        return "line"

    # correlation between two numeric fields → scatter
    if question_type == "correlation":
        return "scatter"

    # ranking
    if question_type == "ranking":
        if row_count > 8:
            return "horizontal_bar"
        return "bar"

    # distribution of a numeric field → histogram
    if question_type == "distribution" and metric in ("mean", "median", "sum"):
        return "histogram"

    # distribution of a categorical with few values → pie
    if question_type == "distribution" and row_count <= 5:
        return "pie"

    # comparison or distribution with many categories → horizontal bar
    if question_type in ("comparison", "distribution") and row_count > 8:
        return "horizontal_bar"

    # aggregation of a single metric → kpi card
    if question_type == "aggregation" and row_count == 1:
        return "kpi_card"

    # rate metrics work best as bar charts (sorted)
    if metric == "rate":
        if row_count > 8:
            return "horizontal_bar"
        return "bar"

    # part-to-whole with few categories
    if row_count <= 5:
        return "pie"

    # default
    return "bar"


def _build_annotations(
    data: list[dict[str, Any]],
    x_field: str,
    y_field: str,
    metric: str,
    top_n: int = 3,
) -> list[str]:
    """
    Generate callout annotations for the top-N rows.
    For rate: format as percentage.
    For count/sum: format with comma separator.
    For mean: format to 2dp.
    """
    if not data or not x_field or not y_field:
        return []

    annotations = []
    for row in data[:top_n]:
        x_val = row.get(x_field, "")
        y_val = row.get(y_field)
        if y_val is None:
            continue
        try:
            y_float = float(y_val)
            if metric == "rate":
                formatted = f"{y_float * 100:.1f}%"
            elif metric in ("count", "sum"):
                formatted = f"{int(y_float):,}"
            else:
                formatted = f"{y_float:.2f}"
            annotations.append(f"{x_val}: {formatted}")
        except (ValueError, TypeError):
            annotations.append(f"{x_val}: {y_val}")

    return annotations


def _build_axis_labels(
    metric: str,
    metric_label: str,
) -> dict[str, str]:
    """Generate human-readable axis labels."""
    if metric == "rate":
        return {
            "y_axis_label": f"{metric_label} (0–100%)",
            "y_format":     "percent",
        }
    elif metric in ("count",):
        return {
            "y_axis_label": "Count",
            "y_format":     "number",
        }
    else:
        return {
            "y_axis_label": metric_label,
            "y_format":     "number",
        }


# ── public API ────────────────────────────────────────────────────

def reason_visualization(
    query_intent:     dict[str, Any],
    execution_result: dict[str, Any],
    schema_profile:   dict[str, Any],
) -> dict[str, Any]:
    """
    Produce a VizSpec from the analytical intent and execution result.

    Returns:
    {
        "chart_type": str,
        "title": str,
        "x_field": str,
        "y_field": str,
        "label_field": str | None,     ← for pie
        "value_field": str | None,     ← for pie
        "data": list[dict],
        "annotations": list[str],
        "y_format": "percent" | "number",
        "y_axis_label": str,
        "why_this_chart": str,
        "confidence": float,
    }
    """
    question_type = query_intent.get("question_type", "distribution")
    metric        = query_intent.get("metric", "count")
    top_n         = query_intent.get("top_n")

    x_field      = execution_result.get("x_field", "")
    y_field      = execution_result.get("y_field", "value")
    data         = execution_result.get("data", [])
    metric_label = execution_result.get("metric_label", "Value")
    result_label = execution_result.get("result_label", "Analysis Result")
    row_count    = execution_result.get("row_count", len(data))

    # ── select chart type ──────────────────────────────────────
    chart_type = _select_chart_type(
        question_type=question_type,
        metric=metric,
        row_count=row_count,
        x_field=x_field,
        schema_profile=schema_profile,
    )

    # ── build annotations (top-3 callouts) ────────────────────
    annotations = _build_annotations(data, x_field, y_field, metric)

    # ── axis labels ────────────────────────────────────────────
    axis_info = _build_axis_labels(metric, metric_label)

    # ── pie/donut uses different field names ───────────────────
    label_field = None
    value_field = None
    if chart_type in ("pie", "donut"):
        label_field = x_field
        value_field = y_field

    # ── why-this-chart rationale ───────────────────────────────
    rationale_map = {
        "horizontal_bar": (
            f"Horizontal bar chosen for {question_type} with {row_count} categories — "
            "labels are readable and values are easy to compare."
        ),
        "bar": (
            f"Bar chart chosen for {question_type} — "
            f"ideal for comparing {row_count} discrete categories."
        ),
        "line": (
            "Line chart chosen for trend analysis — "
            "shows how values change over time continuously."
        ),
        "pie": (
            f"Pie chart chosen for part-to-whole view — "
            f"{row_count} categories fit cleanly in a pie."
        ),
        "histogram": (
            "Histogram chosen for distribution analysis — "
            "shows the spread and skewness of numeric values."
        ),
        "kpi_card": (
            "KPI card chosen for single-metric summary — "
            "surfaces the key number at a glance."
        ),
        "scatter": (
            "Scatter plot chosen for correlation analysis — "
            "shows the relationship between two numeric variables."
        ),
    }
    why = rationale_map.get(chart_type, f"{chart_type} chosen for {question_type}.")

    return {
        "chart_type":   chart_type,
        "title":        result_label,
        "x_field":      x_field,
        "y_field":      y_field,
        "label_field":  label_field,
        "value_field":  value_field,
        "data":         data,
        "annotations":  annotations,
        "y_format":     axis_info["y_format"],
        "y_axis_label": axis_info["y_axis_label"],
        "why_this_chart": why,
        "confidence":   0.88,
    }