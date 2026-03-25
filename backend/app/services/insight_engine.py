from __future__ import annotations

from typing import Any


def _build_insight_from_chart(chart: dict[str, Any]) -> dict[str, Any]:
    title = chart.get("title", "Untitled chart")
    chart_type = chart.get("chart_type", "chart")
    fields = chart.get("fields", [])
    field_text = ", ".join(fields) if fields else "selected fields"

    return {
        "title": title,
        "insight_text": f"The {title.lower()} is included as a {chart_type} to analyze {field_text}.",
        "category": "descriptive",
        "priority": "medium",
        "evidence_fields": fields,
        "confidence": chart.get("confidence", 0.75),
    }


def generate_insights(
    intent: dict[str, Any],
    charts: list[dict[str, Any]],
    schema_profile: dict[str, Any],
) -> dict[str, Any]:
    requested_fields = intent.get("requested_fields", [])
    analysis_tasks = intent.get("analysis_tasks", [])
    dataset_summary = schema_profile.get("dataset_summary", {})

    insights = [_build_insight_from_chart(chart) for chart in charts]

    field_text = ", ".join(requested_fields) if requested_fields else "the selected dataset fields"
    task_text = ", ".join(analysis_tasks) if analysis_tasks else "general BI analysis"

    executive_summary = (
        f"This dashboard analyzes {field_text} across a dataset with "
        f"{dataset_summary.get('rows', 0)} rows and {dataset_summary.get('columns', 0)} columns. "
        f"It is designed to support {task_text} through {len(charts)} recommended visualizations."
    )

    key_takeaways = []
    for chart in charts:
        key_takeaways.append(
            f"{chart.get('title')} helps explain {', '.join(chart.get('fields', []))} using a {chart.get('chart_type')}."
        )

    return {
        "executive_summary": executive_summary,
        "insights": insights,
        "key_takeaways": key_takeaways,
    }