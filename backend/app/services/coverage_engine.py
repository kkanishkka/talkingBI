from __future__ import annotations

from typing import Any


def compute_kpi_coverage(intent: dict[str, Any], charts: list[dict[str, Any]]) -> dict[str, Any]:
    requested_fields = intent.get("requested_fields", [])
    requested_set = set(requested_fields)

    covered_fields = set()
    partially_covered_fields = set()

    for chart in charts:
        chart_fields = set(chart.get("fields", []))
        matched = requested_set.intersection(chart_fields)

        for field in matched:
            covered_fields.add(field)

    uncovered_fields = requested_set - covered_fields - partially_covered_fields

    total_requested = len(requested_set)
    covered_count = len(covered_fields)
    partial_count = len(partially_covered_fields)

    coverage_percentage = 0.0
    if total_requested > 0:
        coverage_percentage = round(((covered_count + 0.5 * partial_count) / total_requested) * 100, 2)

    notes = []
    if total_requested == 0:
        notes.append("No specific fields were requested, so KPI coverage is not applicable.")
    elif coverage_percentage == 100:
        notes.append("All requested fields are covered by the recommended charts.")
    elif coverage_percentage >= 75:
        notes.append("Most requested fields are covered by the recommended charts.")
    else:
        notes.append("Some requested fields are not yet covered and may need additional visualizations.")

    return {
        "requested_fields": sorted(list(requested_set)),
        "covered_fields": sorted(list(covered_fields)),
        "partially_covered_fields": sorted(list(partially_covered_fields)),
        "uncovered_fields": sorted(list(uncovered_fields)),
        "coverage_percentage": coverage_percentage,
        "notes": notes,
    }