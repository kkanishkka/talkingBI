from __future__ import annotations

import re
from typing import Any


KNOWN_ANALYSIS_TASKS = {
    "trend": ["trend", "over time", "time series", "monthly", "daily", "yearly"],
    "comparison": ["compare", "comparison", "versus", "vs", "across"],
    "distribution": ["distribution", "breakdown", "split", "composition"],
    "ranking": ["top", "bottom", "rank", "highest", "lowest"],
    "relationship": ["relationship", "correlation", "impact", "association"],
}


KNOWN_LAYOUT_WORDS = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
}


def _extract_num_visualizations(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(charts|visualizations|layouts|dashboards?)", text.lower())
    if match:
        return int(match.group(1))

    for word, number in KNOWN_LAYOUT_WORDS.items():
        if f"{word} layouts" in text.lower():
            return number

    return None


def _extract_analysis_tasks(text: str) -> list[str]:
    lowered = text.lower()
    tasks = []

    for task, keywords in KNOWN_ANALYSIS_TASKS.items():
        if any(keyword in lowered for keyword in keywords):
            tasks.append(task)

    return tasks


def _extract_requested_fields(text: str, schema_columns: list[str]) -> list[str]:
    lowered = text.lower()
    matched = []

    for col in schema_columns:
        if col.lower() in lowered:
            matched.append(col)

    return matched


def _infer_business_goal(text: str) -> str:
    lowered = text.lower()

    if "dashboard" in lowered:
        return "dashboard generation"
    if "analyze" in lowered or "analysis" in lowered:
        return "data analysis"
    if "summary" in lowered:
        return "insight summary"

    return "general BI exploration"


def parse_intent(user_prompt: str, schema_columns: list[str]) -> dict[str, Any]:
    requested_fields = _extract_requested_fields(user_prompt, schema_columns)
    analysis_tasks = _extract_analysis_tasks(user_prompt)
    num_visualizations = _extract_num_visualizations(user_prompt)

    return {
        "raw_prompt": user_prompt,
        "business_goal": _infer_business_goal(user_prompt),
        "requested_fields": requested_fields,
        "analysis_tasks": analysis_tasks,
        "num_visualizations": num_visualizations or 4,
        "audience": "general",
        "theme": None,
    }