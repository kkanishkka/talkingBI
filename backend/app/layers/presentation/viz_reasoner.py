"""
app/layers/presentation/viz_reasoner.py
══════════════════════════════════════════════════════════════════════
Visualization Reasoner — v3

Changes from v2:
  ① is_kpi_only() helper: detects when result is a scalar (1 row,
    x_field="metric") and returns kpi_card — never a bar/line chart.

  ② _select_chart() updated:
    - aggregation + 1 row → kpi_card (was already there but plan never
      produced 1-row results — now it does via scalar_agg)
    - distribution → pie ONLY if ≤6 categories, otherwise bar
    - ranking → horizontal_bar if >5 rows, bar if ≤5
    - correlation → scatter
    - default → bar (not histogram)

  ③ filter_vizs_by_intent() preserved — unchanged.

  ④ reason_visualization() now detects KPI result and returns
    kpi_card spec with properly formatted kpi_value and kpi_label.

  ⑤ build_dashboard_layouts() unchanged.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.models import (
    ChartType, DashboardLayout, ExecutionResult, LayoutCell,
    MetricType, QueryIntent, QuestionType, VizSpec,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — KPI detection
# ═══════════════════════════════════════════════════════════════════

def is_kpi_result(result: ExecutionResult) -> bool:
    """
    Returns True if the result is a scalar KPI (1 row, x_field="metric").
    These should be rendered as KPI cards, never as charts.
    """
    return (
        result.row_count == 1
        and result.x_field == "metric"
        and result.y_field == "value"
    )


def _format_kpi_value(value: Any, metric: str) -> str:
    """Format a scalar KPI value for display."""
    try:
        f = float(value)
        if metric == MetricType.rate:
            return f"{f * 100:.1f}%"
        if metric in (MetricType.count,):
            return f"{int(f):,}"
        if metric == MetricType.sum:
            if abs(f) >= 1_000_000:
                return f"{f/1_000_000:.2f}M"
            if abs(f) >= 1_000:
                return f"{f/1_000:.1f}K"
            return f"{f:,.2f}"
        return f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(value)


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — chart type selection
# ═══════════════════════════════════════════════════════════════════

def _select_chart(
    question_type: str,
    metric:        str,
    row_count:     int,
    is_kpi:        bool = False,
) -> ChartType:
    """
    Strict rule-based chart selection.
    Every mapping is query-intent driven — no schema guessing.
    """
    # KPI takes absolute priority
    if is_kpi or (question_type == str(QuestionType.aggregation) and row_count <= 1):
        return ChartType.kpi_card

    if question_type == str(QuestionType.trend):
        return ChartType.line

    if question_type == str(QuestionType.correlation):
        return ChartType.scatter

    if question_type == str(QuestionType.ranking):
        return ChartType.horizontal_bar if row_count > 5 else ChartType.bar

    if question_type == str(QuestionType.distribution):
        # Pie only for very few categories, never for large sets
        if row_count <= 6:
            return ChartType.pie
        return ChartType.bar

    if question_type == str(QuestionType.comparison):
        return ChartType.horizontal_bar if row_count > 7 else ChartType.bar

    if question_type == str(QuestionType.aggregation):
        # Multiple-row aggregation (grouped) → bar
        return ChartType.bar

    if metric == str(MetricType.rate):
        return ChartType.horizontal_bar if row_count > 7 else ChartType.bar

    # Safe default — always bar for grouped data
    return ChartType.bar


_CHART_RATIONALE: dict[str, str] = {
    str(ChartType.horizontal_bar): "Horizontal bar — optimal for ranked categorical comparison.",
    str(ChartType.bar):            "Bar chart — best for comparing discrete categories.",
    str(ChartType.line):           "Line chart — shows temporal trend and value evolution.",
    str(ChartType.pie):            "Pie chart — part-to-whole for ≤6 categories.",
    str(ChartType.histogram):      "Histogram — distribution shape of a numeric column.",
    str(ChartType.kpi_card):       "KPI card — single scalar metric, no chart needed.",
    str(ChartType.scatter):        "Scatter plot — correlation between two numeric variables.",
    str(ChartType.area):           "Area chart — cumulative volume over time.",
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — intent-allowed chart filter
# ═══════════════════════════════════════════════════════════════════

_INTENT_ALLOWED_CHARTS: dict[str, set[str]] = {
    str(QuestionType.trend):        {str(ChartType.line), str(ChartType.area)},
    str(QuestionType.ranking):      {str(ChartType.bar), str(ChartType.horizontal_bar)},
    str(QuestionType.comparison):   {str(ChartType.bar), str(ChartType.horizontal_bar)},
    str(QuestionType.distribution): {str(ChartType.histogram), str(ChartType.bar),
                                     str(ChartType.pie), str(ChartType.donut)},
    str(QuestionType.aggregation):  {str(ChartType.kpi_card), str(ChartType.bar),
                                     str(ChartType.horizontal_bar)},
    str(QuestionType.correlation):  {str(ChartType.scatter)},
    str(QuestionType.filtered_lookup): {str(ChartType.bar), str(ChartType.horizontal_bar),
                                        str(ChartType.kpi_card), str(ChartType.pie)},
    str(QuestionType.overview):     {
        str(ChartType.line), str(ChartType.area), str(ChartType.bar),
        str(ChartType.horizontal_bar), str(ChartType.pie), str(ChartType.donut),
        str(ChartType.histogram), str(ChartType.kpi_card), str(ChartType.scatter),
    },
}


def filter_vizs_by_intent(
    visualizations: list[dict[str, Any]],
    intent: QueryIntent,
) -> list[dict[str, Any]]:
    """Remove charts that don't match the current query intent."""
    if not visualizations:
        return []

    qtype   = str(intent.question_type)
    allowed = _INTENT_ALLOWED_CHARTS.get(qtype)
    if not allowed:
        return visualizations

    filtered: list[dict[str, Any]] = []
    for idx, viz in enumerate(visualizations):
        chart_type = str(viz.get("chart_type", ""))
        if idx == 0 and viz.get("is_primary"):
            filtered.append(viz)
            continue
        if chart_type in allowed:
            filtered.append(viz)

    return filtered if filtered else (visualizations[:1] if visualizations else [])


# ═══════════════════════════════════════════════════════════════════
# SECTION 4 — annotation helpers
# ═══════════════════════════════════════════════════════════════════

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
            if metric == str(MetricType.rate):
                fmt = f"{f * 100:.1f}%"
            elif metric in (str(MetricType.count), str(MetricType.sum)):
                fmt = f"{int(f):,}"
            else:
                fmt = f"{f:.2f}"
            out.append(f"{x}: {fmt}")
        except (TypeError, ValueError):
            out.append(f"{x}: {y}")
    return out


def _y_format(metric: str) -> str:
    return "percent" if metric == str(MetricType.rate) else "number"


# ═══════════════════════════════════════════════════════════════════
# SECTION 5 — public API
# ═══════════════════════════════════════════════════════════════════

def reason_visualization(
    intent:         QueryIntent,
    result:         ExecutionResult,
    schema_profile: dict[str, Any],
    is_primary:     bool = False,
) -> VizSpec:
    """
    Build a VizSpec from a QueryIntent + ExecutionResult.

    KPI results get kpi_card type with properly formatted value.
    All other results get the appropriate chart type.
    """
    qt      = str(intent.question_type)
    metric  = str(intent.metric)
    x_field = result.x_field or ""
    y_field = result.y_field or "value"
    data    = result.data

    # ── KPI path ──────────────────────────────────────────────────
    kpi = is_kpi_result(result)
    chart_type = _select_chart(qt, metric, result.row_count, is_kpi=kpi)

    if kpi and data:
        row = data[0]
        raw_value  = row.get("value", 0)
        kpi_label  = row.get("metric", result.metric_label)
        kpi_value  = _format_kpi_value(raw_value, metric)

        return VizSpec(
            chart_type=     ChartType.kpi_card,
            title=          result.result_label,
            x_field=        "metric",
            y_field=        "value",
            data=           data,
            annotations=    [f"{kpi_label}: {kpi_value}"],
            y_format=       _y_format(metric),
            y_axis_label=   result.metric_label,
            why_this_chart= _CHART_RATIONALE[str(ChartType.kpi_card)],
            confidence=     0.95,
            is_primary=     is_primary,
            formula_spec=   result.metric_label,
        )

    # ── Chart path ────────────────────────────────────────────────
    label_field = x_field if chart_type in (
        str(ChartType.pie), str(ChartType.donut)
    ) else None
    value_field = y_field if chart_type in (
        str(ChartType.pie), str(ChartType.donut)
    ) else None
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
        why_this_chart= _CHART_RATIONALE.get(str(chart_type), ""),
        confidence=     0.88,
        is_primary=     is_primary,
        formula_spec=   result.metric_label,
    )


def build_dashboard_layouts(viz_specs: list[VizSpec]) -> list[DashboardLayout]:
    """
    Build 2 layout options from a list of VizSpecs.
    Unchanged from v2.
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
        layout_id="focus", layout_name="Focus View",
        description="Primary analysis full-width, supporting context below.",
        cells=focus_cells,
    ))

    # Overview grid
    overview_cells: list[LayoutCell] = []
    positions = [(1, 6), (7, 6), (1, 6), (7, 6)]
    for i, (cs, cspan) in enumerate(positions[:n]):
        overview_cells.append(LayoutCell(viz_index=i, col_start=cs, col_span=cspan, row_span=1))

    layouts.append(DashboardLayout(
        layout_id="overview", layout_name="Overview Grid",
        description="Equal-weight 2×2 grid for side-by-side comparison.",
        cells=overview_cells,
    ))

    return layouts