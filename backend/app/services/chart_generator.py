"""
app/services/chart_generator.py
══════════════════════════════════════════════════════════════════════
Chart Generator

Converts MultiExecutionResult → list of VizSpec dicts ready for the
frontend. Each successful ChartResult becomes one VizSpec.

Also converts KPIResults into kpi_card VizSpecs.

This replaces the single reason_visualization() call in the old
pipeline with a batch pass that covers all sub-plans.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.multi_executor import ChartResult, KPIResult, MultiExecutionResult
from app.services.planner import SubPlan

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Formatting helpers
# ═══════════════════════════════════════════════════════════════════

def _fmt(value: Any, metric: str) -> str:
    try:
        f = float(value)
        if metric == "rate":
            return f"{f * 100:.1f}%"
        if metric in ("count", "sum"):
            return f"{int(f):,}"
        return f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _annotations(data: list[dict], x: str, y: str, metric: str, n: int = 3) -> list[str]:
    out = []
    for row in data[:n]:
        xv = row.get(x, "?")
        yv = row.get(y)
        if yv is None:
            continue
        out.append(f"{xv}: {_fmt(yv, metric)}")
    return out


_RATIONALE = {
    "horizontal_bar": "Horizontal bar — optimal for ranked categorical comparison.",
    "bar":            "Bar chart — comparing discrete categories.",
    "line":           "Line chart — temporal trend.",
    "pie":            "Pie chart — part-to-whole for ≤6 categories.",
    "kpi_card":       "KPI card — single scalar metric.",
    "scatter":        "Scatter plot — correlation between two variables.",
}


# ═══════════════════════════════════════════════════════════════════
# KPI → VizSpec
# ═══════════════════════════════════════════════════════════════════

def _kpi_to_viz(kr: KPIResult, is_primary: bool) -> dict[str, Any]:
    return {
        "chart_type":     "kpi_card",
        "title":          kr.definition.label,
        "x_field":        "metric",
        "y_field":        "value",
        "label_field":    None,
        "value_field":    None,
        "data":           [{"metric": kr.definition.label, "value": kr.value}],
        "annotations":    [f"{kr.definition.label}: {kr.formatted}"],
        "y_format":       "number",
        "y_axis_label":   kr.definition.label,
        "why_this_chart": _RATIONALE["kpi_card"],
        "confidence":     0.95,
        "is_primary":     is_primary,
        "formula_spec":   kr.definition.formula,
        "kpi_value":      kr.formatted,
        "kpi_label":      kr.definition.label,
    }


# ═══════════════════════════════════════════════════════════════════
# ChartResult → VizSpec
# ═══════════════════════════════════════════════════════════════════

def _chart_to_viz(cr: ChartResult, is_primary: bool) -> dict[str, Any]:
    sp     = cr.sub_plan
    result = cr.execution_result
    metric = sp.metric
    x      = result.x_field or sp.dimension or ""
    y      = result.y_field or "value"
    data   = result.data
    hint   = sp.chart_hint or "bar"

    label_field = x if hint in ("pie", "donut") else None
    value_field = y if hint in ("pie", "donut") else None

    return {
        "chart_type":     hint,
        "title":          sp.label or result.result_label,
        "x_field":        x,
        "y_field":        y,
        "label_field":    label_field,
        "value_field":    value_field,
        "data":           data,
        "annotations":    _annotations(data, x, y, metric),
        "y_format":       "percent" if metric == "rate" else "number",
        "y_axis_label":   result.metric_label,
        "why_this_chart": _RATIONALE.get(hint, ""),
        "confidence":     0.88,
        "is_primary":     is_primary,
        "formula_spec":   sp.formula,
    }


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def generate_charts(
    execution: MultiExecutionResult,
    max_charts: int = 6,
) -> list[dict[str, Any]]:
    """
    Convert MultiExecutionResult → list of VizSpec dicts.

    Order: KPI cards first (is_primary=True for first),
           then chart panels (is_primary=True for first chart).

    Returns at most max_charts items.
    """
    vizs: list[dict[str, Any]] = []

    # KPI cards
    for i, kr in enumerate(execution.kpi_results):
        if kr.success and kr.value is not None:
            vizs.append(_kpi_to_viz(kr, is_primary=(i == 0 and not execution.successful_charts)))

    # Chart panels
    first_chart = True
    for cr in execution.successful_charts[:max_charts]:
        vizs.append(_chart_to_viz(cr, is_primary=first_chart))
        first_chart = False

    logger.info("chart_generator: produced %d vizs", len(vizs))
    return vizs[:max_charts + len(execution.kpi_results)]