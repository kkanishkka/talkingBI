"""
app/layers/presentation/dashboard_composer.py
══════════════════════════════════════════════════════════════════════
Query-Aware Dashboard Composer — v2

v2 changes:
  ① KPI results (is_kpi_only) return immediately with just the primary
    card — no table widget, no trend companion, no KPI card duplicate.
  ② _build_kpi_card() now reads the pre-formatted value from the viz
    data (set by viz_reasoner) instead of re-formatting.
  ③ generate_followup_suggestions() skips distribution suggestion for
    KPI-only results since the result has no grouping to redistribute.
  ④ Trend companion is only built when a date column exists AND the
    primary intent is not already trend/distribution.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.models import (
    ChartType, ExecutionResult, MetricType,
    QueryIntent, QuestionType,
)
from app.layers.presentation.viz_reasoner import is_kpi_result, reason_visualization

logger = logging.getLogger(__name__)

_MAX_WIDGETS = 4


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — widget builders
# ═══════════════════════════════════════════════════════════════════

def _build_kpi_summary_card(
    intent: QueryIntent,
    result: ExecutionResult,
) -> Optional[dict[str, Any]]:
    """
    Build a KPI summary card showing the #1 ranked item.
    Only added for ranking/comparison results with ≥2 rows.
    """
    qt = str(intent.question_type)
    if qt not in (str(QuestionType.ranking), str(QuestionType.comparison)):
        return None
    if result.row_count < 2 or not result.data:
        return None

    top_row   = result.data[0]
    x_field   = result.x_field or ""
    y_field   = result.y_field or "value"
    top_label = str(top_row.get(x_field, "Top"))
    top_value = top_row.get(y_field)
    if top_value is None:
        return None

    metric = str(intent.metric)
    try:
        fv = float(top_value)
        if metric == MetricType.rate:
            formatted = f"{fv * 100:.1f}%"
        elif metric in (MetricType.count, MetricType.sum):
            if abs(fv) >= 1_000_000:
                formatted = f"{fv/1_000_000:.2f}M"
            elif abs(fv) >= 1_000:
                formatted = f"{fv/1_000:.1f}K"
            else:
                formatted = f"{int(fv):,}"
        else:
            formatted = f"{fv:,.2f}"
    except (TypeError, ValueError):
        formatted = str(top_value)

    return {
        "chart_type":     ChartType.kpi_card,
        "title":          f"Top {x_field.replace('_', ' ').title()}",
        "subtitle":       result.metric_label,
        "kpi_value":      formatted,
        "kpi_label":      top_label,
        "x_field":        "metric",
        "y_field":        "value",
        "data":           [{"metric": top_label, "value": top_value}],
        "is_primary":     False,
        "confidence":     0.95,
        "why_this_chart": "KPI card — highlights the single top performer at a glance.",
        "annotations":    [],
        "y_format":       "percent" if metric == MetricType.rate else "number",
        "y_axis_label":   result.metric_label,
        "formula_spec":   result.metric_label,
    }


def _build_table_widget(
    intent: QueryIntent,
    result: ExecutionResult,
) -> Optional[dict[str, Any]]:
    """
    Tabular ranking view. Only for ranking/comparison with ≥2 rows.
    Adds rank numbers.
    """
    qt = str(intent.question_type)
    if qt not in (str(QuestionType.ranking), str(QuestionType.comparison)):
        return None
    if result.row_count < 2 or not result.data:
        return None

    ranked = [{"rank": i + 1, **row} for i, row in enumerate(result.data[:25])]
    return {
        "chart_type":     "table",
        "title":          f"Ranking Table — {result.result_label}",
        "x_field":        result.x_field,
        "y_field":        result.y_field,
        "data":           ranked,
        "is_primary":     False,
        "confidence":     0.90,
        "why_this_chart": "Data table — exact values alongside the visualization.",
        "annotations":    [],
        "y_format":       "number",
        "y_axis_label":   result.metric_label,
        "formula_spec":   result.metric_label,
    }


def _build_trend_companion(
    intent:         QueryIntent,
    schema_profile: dict[str, Any],
    df:             Any,
) -> Optional[dict[str, Any]]:
    """
    Adds a trend-over-time chart alongside a ranking/comparison result,
    when a date column exists. Only useful for aggregation contexts.
    """
    from app.core.models import QueryIntent as QI
    from app.layers.reasoning.analysis_planner import build_analysis_plan
    from app.layers.reasoning.analysis_executor import execute_plan
    from app.layers.reasoning.reflection import validate_result

    qt = str(intent.question_type)
    if qt in (str(QuestionType.trend), str(QuestionType.correlation),
              str(QuestionType.distribution)):
        return None

    cols      = schema_profile.get("columns", [])
    date_cols = [c for c in cols if c["role"] == "date"]
    if not date_cols:
        return None

    date_col = date_cols[0]["name"]
    try:
        trend_intent = QI(
            question_type=    QuestionType.trend,
            metric=           intent.metric,
            target_variable=  intent.target_variable,
            time_column=      date_col,
            primary_dimension=date_col,
            sort_direction=   "asc",
            top_n=            50,
            raw_prompt=       f"Trend of {intent.metric} over time",
        )
        plan   = build_analysis_plan(trend_intent, schema_profile)
        result = execute_plan(plan, df)
        report = validate_result(trend_intent, plan, result)

        if not report.valid or not result.data or is_kpi_result(result):
            return None

        viz = reason_visualization(trend_intent, result, schema_profile, is_primary=False)
        return viz.dict()

    except Exception as exc:
        logger.debug("Trend companion failed: %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — main composition function
# ═══════════════════════════════════════════════════════════════════

def compose_dashboard(
    intent:         QueryIntent,
    primary_result: ExecutionResult,
    primary_viz:    dict[str, Any],
    schema_profile: dict[str, Any],
    df:             Any,
) -> list[dict[str, Any]]:
    """
    Build a query-aware widget list (max _MAX_WIDGETS).

    KPI results:  primary kpi_card only — nothing else.
    ranking:      primary bar + kpi_card + table (3 max)
    comparison:   primary bar + kpi_card + table (3 max)
    aggregation:  primary chart + kpi_card (2 max)
    trend:        primary line only
    distribution: primary chart only
    correlation:  primary scatter only
    """
    # ── KPI path: scalar result — no additional widgets ────────────
    if is_kpi_result(primary_result):
        return [primary_viz]

    widgets: list[dict[str, Any]] = [primary_viz]
    qt = str(intent.question_type)

    # ── Ranking / Comparison ───────────────────────────────────────
    if qt in (str(QuestionType.ranking), str(QuestionType.comparison)):
        kpi = _build_kpi_summary_card(intent, primary_result)
        if kpi and len(widgets) < _MAX_WIDGETS:
            widgets.append(kpi)

        table = _build_table_widget(intent, primary_result)
        if table and len(widgets) < _MAX_WIDGETS:
            widgets.append(table)

    # ── Aggregation (grouped, not scalar) ─────────────────────────
    elif qt == str(QuestionType.aggregation):
        kpi = _build_kpi_summary_card(intent, primary_result)
        if kpi and len(widgets) < _MAX_WIDGETS:
            widgets.append(kpi)

    # ── All other types: primary only ─────────────────────────────
    # trend, distribution, correlation → primary is self-contained

    # ── Optional trend companion ──────────────────────────────────
    if len(widgets) < _MAX_WIDGETS and qt not in (
        str(QuestionType.trend),
        str(QuestionType.correlation),
        str(QuestionType.distribution),
        str(QuestionType.aggregation),
    ):
        companion = _build_trend_companion(intent, schema_profile, df)
        if companion:
            widgets.append(companion)

    logger.info(
        "DashboardComposer: intent=%s → %d widget(s): %s",
        qt, len(widgets),
        [w.get("chart_type") for w in widgets],
    )
    return widgets[:_MAX_WIDGETS]


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — follow-up suggestions
# ═══════════════════════════════════════════════════════════════════

def generate_followup_suggestions(
    intent:         QueryIntent,
    result:         ExecutionResult,
    schema_profile: dict[str, Any],
) -> list[str]:
    """
    Generate 3–4 contextual follow-up suggestions shown as clickable chips.
    Fully schema-driven — no hardcoding.
    """
    cols    = schema_profile.get("columns", [])
    dims    = [c["name"] for c in cols
               if c["role"] == "dimension"
               and c.get("semantic_hint") not in ("likely_id", "high_cardinality")]
    metrics = [c["name"] for c in cols if c["role"] == "metric"]
    dates   = [c["name"] for c in cols if c["role"] == "date"]

    qt          = str(intent.question_type)
    dim         = intent.primary_dimension or (dims[0] if dims else "category")
    metric_name = intent.target_variable or (metrics[0] if metrics else "value")

    suggestions: list[str] = []

    # ── Alternate dimension ────────────────────────────────────────
    alt_dims = [d for d in dims if d != intent.primary_dimension]
    if alt_dims:
        suggestions.append(f"Show same analysis by {alt_dims[0]}")

    # ── Alternate metric ───────────────────────────────────────────
    alt_metrics = [m for m in metrics if m != intent.target_variable]
    if alt_metrics:
        suggestions.append(f"Compare {alt_metrics[0]} by {dim}")

    # ── Trend suggestion (skip if already trend or KPI with no dim) ─
    if dates and qt != str(QuestionType.trend) and intent.primary_dimension:
        suggestions.append(f"Show {metric_name} trend over time")

    # ── Top-N variation ────────────────────────────────────────────
    if qt == str(QuestionType.ranking):
        current_n = intent.top_n or 10
        alt_n     = 10 if current_n == 5 else 5
        suggestions.append(f"Show top {alt_n} instead")

    # ── Distribution (not for KPI-only) ───────────────────────────
    if qt not in (str(QuestionType.distribution), str(QuestionType.aggregation)):
        if metrics and intent.primary_dimension:
            suggestions.append(f"Show distribution of {metric_name}")

    return suggestions[:4]