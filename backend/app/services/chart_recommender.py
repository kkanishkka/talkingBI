from __future__ import annotations

from typing import Any


def _find_column_profile(schema_profile: dict[str, Any], column_name: str) -> dict[str, Any] | None:
    for col in schema_profile.get("columns", []):
        if col["name"] == column_name:
            return col
    return None


def _is_identifier_column(col_profile: dict[str, Any]) -> bool:
    name = col_profile["name"].lower()
    return name.endswith("_id") or name == "id"


def _recommend_chart_for_column(
    column_name: str,
    col_profile: dict[str, Any],
    analysis_tasks: list[str],
) -> dict[str, Any] | None:
    role = col_profile.get("role")
    dtype = col_profile.get("dtype", "")
    unique_count = col_profile.get("unique_count", 0)

    if _is_identifier_column(col_profile):
        return None

    if role == "date":
        return {
            "chart_type": "line",
            "title": f"{column_name} trend over time",
            "fields": [column_name],
            "what_it_shows": f"This chart shows how {column_name} changes over time.",
            "why_this_chart": "A line chart is best for showing trends across time.",
            "confidence": 0.9,
        }

    if role == "dimension":
        if "distribution" in analysis_tasks or "comparison" in analysis_tasks:
            if unique_count <= 6:
                return {
                    "chart_type": "bar",
                    "title": f"{column_name} distribution",
                    "fields": [column_name],
                    "what_it_shows": f"This chart shows the distribution of records across {column_name}.",
                    "why_this_chart": "A bar chart is effective for comparing category counts clearly.",
                    "confidence": 0.88,
                }
            return {
                "chart_type": "horizontal_bar",
                "title": f"{column_name} comparison",
                "fields": [column_name],
                "what_it_shows": f"This chart compares categories in {column_name}.",
                "why_this_chart": "A horizontal bar chart is better when categories may be longer or more numerous.",
                "confidence": 0.84,
            }

        return {
            "chart_type": "bar",
            "title": f"{column_name} overview",
            "fields": [column_name],
            "what_it_shows": f"This chart gives an overview of the categories in {column_name}.",
            "why_this_chart": "A bar chart is a safe default for category-based analysis.",
            "confidence": 0.75,
        }

    if role == "metric":
        if "comparison" in analysis_tasks:
            return {
                "chart_type": "histogram",
                "title": f"{column_name} distribution",
                "fields": [column_name],
                "what_it_shows": f"This chart shows the spread of {column_name} values.",
                "why_this_chart": "A histogram helps understand how numeric values are distributed.",
                "confidence": 0.82,
            }

        return {
            "chart_type": "kpi_card",
            "title": f"{column_name} summary",
            "fields": [column_name],
            "what_it_shows": f"This card summarizes the key value of {column_name}.",
            "why_this_chart": "A KPI card is useful for highlighting an important numeric field quickly.",
            "confidence": 0.7,
        }

    return None


def recommend_charts(intent: dict[str, Any], schema_profile: dict[str, Any]) -> list[dict[str, Any]]:
    requested_fields = intent.get("requested_fields", [])
    analysis_tasks = intent.get("analysis_tasks", [])
    num_visualizations = intent.get("num_visualizations", 4)

    chart_specs: list[dict[str, Any]] = []

    for field in requested_fields:
        col_profile = _find_column_profile(schema_profile, field)
        if not col_profile:
            continue

        chart = _recommend_chart_for_column(field, col_profile, analysis_tasks)
        if chart:
            chart_specs.append(chart)

    # fallback if request matched too few fields
    if not chart_specs:
        for col_profile in schema_profile.get("columns", []):
            if _is_identifier_column(col_profile):
                continue
            chart = _recommend_chart_for_column(col_profile["name"], col_profile, analysis_tasks)
            if chart:
                chart_specs.append(chart)
            if len(chart_specs) >= num_visualizations:
                break

    return chart_specs[:num_visualizations]