"""
app/services/chart_recommender.py
────────────────────────────────────────────────────────────────────
Recommends chart types based purely on schema roles and intent.
Zero hardcoded column names — every decision is role-driven.
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from typing import Any


def _find_column_profile(
    schema_profile: dict[str, Any], column_name: str
) -> dict[str, Any] | None:
    for col in schema_profile.get("columns", []):
        if col["name"] == column_name:
            return col
    return None


def _is_identifier_column(col_profile: dict[str, Any]) -> bool:
    name = col_profile["name"].lower()
    return (
        name.endswith("_id")
        or name == "id"
        or name.endswith("_key")
        or name == "index"
        or name == "rownum"
    )


def _recommend_chart_for_column(
    col_profile: dict[str, Any],
    analysis_tasks: list[str],
) -> dict[str, Any] | None:
    """
    Pure role-based chart recommendation.
    Returns a chart spec dict or None if the column should be skipped.
    """
    column_name = col_profile["name"]
    role = col_profile.get("role")
    unique_count = col_profile.get("unique_count", 0)
    null_pct = col_profile.get("null_percentage", 0)

    if _is_identifier_column(col_profile):
        return None

    # ── DATE columns → always line chart ──────────────────────────
    if role == "date":
        return {
            "chart_type": "line",
            "title": f"Trend over {column_name}",
            "fields": [column_name],
            "what_it_shows": f"How values change across {column_name} over time.",
            "why_this_chart": "Line charts are optimal for revealing temporal trends and seasonality.",
            "confidence": 0.92,
        }

    # ── DIMENSION columns → bar / pie / horizontal_bar ─────────────
    if role == "dimension":
        if unique_count == 0:
            return None

        has_distribution = "distribution" in analysis_tasks or "comparison" in analysis_tasks
        has_ranking = "ranking" in analysis_tasks

        # very low cardinality → pie
        if unique_count <= 4 and not has_ranking:
            return {
                "chart_type": "pie",
                "title": f"{column_name} breakdown",
                "fields": [column_name],
                "what_it_shows": f"Proportional split of records across {column_name} categories.",
                "why_this_chart": "A pie chart clearly shows part-to-whole relationships for low-cardinality fields.",
                "confidence": 0.87,
            }

        # low-medium cardinality → bar
        if unique_count <= 12:
            return {
                "chart_type": "bar",
                "title": f"{column_name} distribution",
                "fields": [column_name],
                "what_it_shows": f"Count of records for each category in {column_name}.",
                "why_this_chart": "Bar charts excel at comparing discrete categories side by side.",
                "confidence": 0.88,
            }

        # high cardinality → horizontal bar (labels fit better)
        return {
            "chart_type": "horizontal_bar",
            "title": f"Top {column_name} categories",
            "fields": [column_name],
            "what_it_shows": f"Top categories in {column_name} ranked by frequency.",
            "why_this_chart": "Horizontal bars handle longer category labels and top-N rankings well.",
            "confidence": 0.82,
        }

    # ── METRIC columns → histogram or KPI card ────────────────────
    if role == "metric":
        # if distribution analysis requested → histogram
        if "distribution" in analysis_tasks or "comparison" in analysis_tasks:
            return {
                "chart_type": "histogram",
                "title": f"{column_name} value distribution",
                "fields": [column_name],
                "what_it_shows": f"Frequency distribution of {column_name} values across the dataset.",
                "why_this_chart": "Histograms expose skewness, outliers and clustering in numeric data.",
                "confidence": 0.85,
            }

        # default → KPI card for summary stats
        return {
            "chart_type": "kpi_card",
            "title": f"{column_name} summary",
            "fields": [column_name],
            "what_it_shows": f"Key statistics for {column_name}: sum, mean, median, max.",
            "why_this_chart": "KPI cards surface high-level numeric summaries at a glance.",
            "confidence": 0.78,
        }

    return None


def recommend_charts(
    intent: dict[str, Any], schema_profile: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Build a ranked list of chart recommendations for the given intent.

    Priority:
      1. Fields explicitly requested in the prompt
      2. Date columns (always valuable)
      3. Low-cardinality dimensions
      4. Metrics
      5. Remaining dimensions
    """
    requested_fields = intent.get("requested_fields", [])
    analysis_tasks = intent.get("analysis_tasks", [])
    num_visualizations = intent.get("num_visualizations", 4)

    all_columns = schema_profile.get("columns", [])
    chart_specs: list[dict[str, Any]] = []
    seen_fields: set[str] = set()

    def _add(col_profile: dict[str, Any]) -> None:
        name = col_profile["name"]
        if name in seen_fields:
            return
        chart = _recommend_chart_for_column(col_profile, analysis_tasks)
        if chart:
            chart_specs.append(chart)
            seen_fields.add(name)

    # pass 1 — explicitly requested fields
    for field in requested_fields:
        cp = _find_column_profile(schema_profile, field)
        if cp:
            _add(cp)

    # pass 2 — date columns (high analytical value)
    for col in all_columns:
        if col["role"] == "date":
            _add(col)
        if len(chart_specs) >= num_visualizations:
            break

    # pass 3 — low-cardinality dimensions first (most visual impact)
    for col in sorted(
        [c for c in all_columns if c["role"] == "dimension"],
        key=lambda c: c["unique_count"],
    ):
        _add(col)
        if len(chart_specs) >= num_visualizations:
            break

    # pass 4 — metrics
    for col in all_columns:
        if col["role"] == "metric":
            _add(col)
        if len(chart_specs) >= num_visualizations:
            break

    # pass 5 — remaining columns
    for col in all_columns:
        _add(col)
        if len(chart_specs) >= num_visualizations:
            break

    return chart_specs[:num_visualizations]