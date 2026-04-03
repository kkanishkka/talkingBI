"""
app/layers/presentation/viz_reasoner.py
══════════════════════════════════════════════════════════════════════
Visualization Reasoner

Responsibilities:
  1. Select the best primary chart for a query/result pair
  2. Filter extra charts so dashboard stays query-aware
  3. Build dashboard layouts from VizSpec objects

Phase 1 additions:
  - filter_vizs_by_intent()
  - intent-aware allowed chart mapping
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any

from app.core.models import (
    ChartType, DashboardLayout, ExecutionResult, LayoutCell,
    MetricType, QueryIntent, QuestionType, VizSpec,
)

import logging
logger = logging.getLogger(__name__)


# ── Chart selection ───────────────────────────────────────────────

def _select_chart(
    question_type: str,
    metric:        str,
    row_count:     int,
) -> ChartType:
    if question_type == QuestionType.trend:
        return ChartType.line

    if question_type == QuestionType.correlation:
        return ChartType.scatter

    if question_type == QuestionType.ranking:
        return ChartType.horizontal_bar if row_count > 7 else ChartType.bar

    if question_type == QuestionType.distribution:
        if metric in (MetricType.mean, MetricType.median, MetricType.sum):
            return ChartType.histogram
        if row_count <= 5:
            return ChartType.pie
        return ChartType.bar

    if question_type == QuestionType.comparison:
        return ChartType.horizontal_bar if row_count > 7 else ChartType.bar

    if question_type == QuestionType.aggregation and row_count == 1:
        return ChartType.kpi_card

    if metric == MetricType.rate:
        return ChartType.horizontal_bar if row_count > 7 else ChartType.bar

    if row_count <= 5:
        return ChartType.pie

    return ChartType.bar


_RATIONALE: dict[str, str] = {
    ChartType.horizontal_bar: "Horizontal bar chart — optimal for ranked categorical comparison with readable labels.",
    ChartType.bar:            "Bar chart — best for comparing a small number of discrete categories.",
    ChartType.line:           "Line chart — shows temporal trends and value evolution over time.",
    ChartType.pie:            "Pie chart — shows part-to-whole proportions for ≤5 categories.",
    ChartType.histogram:      "Histogram — reveals distribution shape, skewness and clustering of numeric values.",
    ChartType.kpi_card:       "KPI card — highlights a single summary statistic at a glance.",
    ChartType.scatter:        "Scatter plot — visualises correlation between two numeric variables.",
    ChartType.area:           "Area chart — emphasises cumulative volume over a continuous axis.",
}


# ── Query-aware filtering ─────────────────────────────────────────

_INTENT_ALLOWED_CHARTS: dict[str, set[str]] = {
    str(QuestionType.trend): {
        str(ChartType.line),
        str(ChartType.area),
    },
    str(QuestionType.ranking): {
        str(ChartType.bar),
        str(ChartType.horizontal_bar),
    },
    str(QuestionType.comparison): {
        str(ChartType.bar),
        str(ChartType.horizontal_bar),
    },
    str(QuestionType.distribution): {
        str(ChartType.histogram),
        str(ChartType.bar),
        str(ChartType.pie),
        str(ChartType.donut),
    },
    str(QuestionType.aggregation): {
        str(ChartType.kpi_card),
        str(ChartType.bar),
        str(ChartType.horizontal_bar),
    },
    str(QuestionType.correlation): {
        str(ChartType.scatter),
    },
    str(QuestionType.filtered_lookup): {
        str(ChartType.bar),
        str(ChartType.horizontal_bar),
        str(ChartType.kpi_card),
        str(ChartType.pie),
    },
    str(QuestionType.overview): {
        str(ChartType.line),
        str(ChartType.area),
        str(ChartType.bar),
        str(ChartType.horizontal_bar),
        str(ChartType.pie),
        str(ChartType.donut),
        str(ChartType.histogram),
        str(ChartType.kpi_card),
        str(ChartType.scatter),
    },
}


def filter_vizs_by_intent(
    visualizations: list[dict[str, Any]],
    intent: QueryIntent,
) -> list[dict[str, Any]]:
    """
    Keep only charts relevant to the current query intent.

    Rules:
    - Always preserve the primary chart
    - For non-overview intents, remove overview charts whose chart_type
      is not allowed for the detected question_type
    - If filtering removes everything except the primary chart, that's okay
    """
    if not visualizations:
        return []

    qtype = str(intent.question_type)
    allowed = _INTENT_ALLOWED_CHARTS.get(qtype)

    if not allowed:
        return visualizations

    filtered: list[dict[str, Any]] = []

    for idx, viz in enumerate(visualizations):
        chart_type = str(viz.get("chart_type", ""))

        # Always keep first chart if it is the primary analysis result
        if idx == 0 and viz.get("is_primary"):
            filtered.append(viz)
            continue

        if chart_type in allowed:
            filtered.append(viz)

    # Safety fallback: if everything got filtered out, keep original first chart
    if not filtered and visualizations:
        filtered.append(visualizations[0])

    return filtered


def _format_annotations(
    data:    list[dict[str, Any]],
    x_field: str,
    y_field: str,
    metric:  str,
    top_n:   int = 3,
) -> list[str]:
    out = []
    for row in data[:top_n]:
        x = row.get(x_field, "?")
        y = row.get(y_field)
        if y is None:
            continue
        try:
            f = float(y)
            if metric == MetricType.rate:
                fmt = f"{f * 100:.1f}%"
            elif metric in (MetricType.count, MetricType.sum):
                fmt = f"{int(f):,}"
            else:
                fmt = f"{f:.2f}"
            out.append(f"{x}: {fmt}")
        except (TypeError, ValueError):
            out.append(f"{x}: {y}")
    return out


def _y_format(metric: str) -> str:
    return "percent" if metric == MetricType.rate else "number"


# ── Public API ────────────────────────────────────────────────────

def reason_visualization(
    intent:         QueryIntent,
    result:         ExecutionResult,
    schema_profile: dict[str, Any],
    is_primary:     bool = False,
) -> VizSpec:
    qt      = str(intent.question_type)
    metric  = str(intent.metric)
    x_field = result.x_field or ""
    y_field = result.y_field or "value"
    data    = result.data

    chart_type  = _select_chart(qt, metric, result.row_count)
    label_field = x_field if chart_type in (ChartType.pie, ChartType.donut) else None
    value_field = y_field if chart_type in (ChartType.pie, ChartType.donut) else None
    annotations = _format_annotations(data, x_field, y_field, metric)

    return VizSpec(
        chart_type=     chart_type,
        title=          result.result_label,
        x_field=        x_field,
        y_field=        y_field,
        label_field=    label_field,
        value_field=    value_field,
        data=           data,
        annotations=    annotations,
        y_format=       _y_format(metric),
        y_axis_label=   result.metric_label,
        why_this_chart= _RATIONALE.get(chart_type, ""),
        confidence=     0.88,
        is_primary=     is_primary,
        formula_spec=   result.metric_label,
    )


def build_dashboard_layouts(viz_specs: list[VizSpec]) -> list[DashboardLayout]:
    """
    Build 2 dashboard layout options from a list of VizSpecs.
    Layout 1 — Focus: primary chart full-width, supporting below.
    Layout 2 — Overview: 2×2 equal grid.
    """
    n = len(viz_specs)
    if n == 0:
        return []

    layouts: list[DashboardLayout] = []

    # Focus layout
    focus_cells: list[LayoutCell] = []
    if n >= 1:
        focus_cells.append(LayoutCell(viz_index=0, col_start=1, col_span=12, row_span=2))
    if n >= 2:
        col_span = 6 if n >= 3 else 12
        focus_cells.append(LayoutCell(viz_index=1, col_start=1, col_span=col_span, row_span=1))
    if n >= 3:
        focus_cells.append(LayoutCell(viz_index=2, col_start=7, col_span=6, row_span=1))
    if n >= 4:
        focus_cells.append(LayoutCell(viz_index=3, col_start=1, col_span=12, row_span=1))

    layouts.append(DashboardLayout(
        layout_id="focus",
        layout_name="Focus View",
        description="Primary analysis full-width, supporting context below.",
        cells=focus_cells,
    ))

    # Overview grid
    overview_cells: list[LayoutCell] = []
    positions = [(1, 6), (7, 6), (1, 6), (7, 6)]
    for i, (cs, cspan) in enumerate(positions[:n]):
        overview_cells.append(LayoutCell(viz_index=i, col_start=cs, col_span=cspan, row_span=1))

    layouts.append(DashboardLayout(
        layout_id="overview",
        layout_name="Overview Grid",
        description="Equal-weight 2×2 grid for side-by-side comparison.",
        cells=overview_cells,
    ))

    return layouts