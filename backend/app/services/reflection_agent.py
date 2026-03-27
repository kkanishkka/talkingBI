"""
app/services/reflection_agent.py
════════════════════════════════════════════════════════════════════
Agent 4: Reflector / Validator

Responsibility:
  After the Executor runs, validate that:
    1. The result is non-empty and has reasonable row counts
    2. The metric makes sense (rate values between 0-1, counts positive)
    3. The intended metric matches what was computed
    4. No obvious data quality issues (all-NaN, single-row results)
    5. The chart will not be misleading (e.g. count shown when rate asked)

  Outputs a ValidationReport:
  {
    "valid": bool,
    "issues": [str],          ← blocking problems
    "warnings": [str],        ← non-blocking notices
    "corrections": [str],     ← what was auto-fixed
    "quality_score": 0.0-1.0
  }

  The dashboard only renders charts flagged as valid=True.
  Issues are surfaced to the user if valid=False.

Usage:
  from app.services.reflection_agent import validate_result
  report = validate_result(query_intent, plan, execution_result)
════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any


# ── validators ────────────────────────────────────────────────────

def _check_empty(result: dict[str, Any]) -> list[str]:
    issues = []
    if not result.get("success"):
        issues.append(f"Execution failed: {result.get('error', 'unknown error')}")
    elif not result.get("data"):
        issues.append("Execution returned no data rows.")
    return issues


def _check_metric_range(
    intent: dict[str, Any],
    result: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """
    For rate metrics: values should be in [0, 1].
    For count: values should be non-negative integers.
    """
    issues:   list[str] = []
    warnings: list[str] = []

    metric  = intent.get("metric", "count")
    y_field = result.get("y_field", "value")
    data    = result.get("data", [])

    if not data:
        return issues, warnings

    values = [
        float(row[y_field])
        for row in data
        if row.get(y_field) is not None
    ]
    if not values:
        return issues, warnings

    max_val = max(values)
    min_val = min(values)

    if metric == "rate":
        if max_val > 1.0:
            issues.append(
                f"Rate values exceed 1.0 (max={max_val:.3f}). "
                "This suggests count was computed instead of rate. "
                "Check that agg_fn='rate' was used correctly."
            )
        if min_val < 0:
            issues.append(f"Rate values are negative (min={min_val:.3f}). Data error.")
        if max_val <= 0.001:
            warnings.append(
                f"Rate values are extremely small (max={max_val:.5f}). "
                "Verify the rate_value matches the positive class in your data."
            )

    elif metric == "count":
        if max_val < 1:
            warnings.append(
                "Count values are less than 1 — results may be normalised proportions."
            )
        if min_val < 0:
            issues.append("Count values are negative — unexpected data issue.")

    return issues, warnings


def _check_cardinality(
    intent: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    """Warn about extreme cardinality in results."""
    warnings: list[str] = []
    row_count = result.get("row_count", 0)

    if row_count == 1:
        warnings.append(
            "Result has only 1 row — groupby may have matched only one category. "
            "Verify the primary_dimension is correct."
        )
    elif row_count > 50:
        warnings.append(
            f"Result has {row_count} rows — consider adding top_n to limit to 10-20 "
            "categories for a readable chart."
        )
    return warnings


def _check_single_value(result: dict[str, Any]) -> list[str]:
    """Detect if all values are identical (useless chart)."""
    warnings: list[str] = []
    y_field = result.get("y_field", "value")
    data    = result.get("data", [])

    if not data or len(data) < 2:
        return warnings

    values = {
        row[y_field]
        for row in data
        if row.get(y_field) is not None
    }
    if len(values) == 1:
        warnings.append(
            f"All result rows have identical value ({next(iter(values))}). "
            "This chart will show no variation and may not be informative."
        )
    return warnings


def _check_metric_mismatch(
    intent: dict[str, Any],
    plan: dict[str, Any],
) -> list[str]:
    """Detect if the plan computes a different metric than the intent requested."""
    warnings: list[str] = []

    intent_metric = intent.get("metric")
    plan_ops = plan.get("operations", [])

    for op in plan_ops:
        if op.get("op") == "groupby_agg":
            plan_agg = op.get("args", {}).get("agg_fn")
            if plan_agg and plan_agg != intent_metric:
                warnings.append(
                    f"Metric mismatch: intent requested '{intent_metric}' "
                    f"but plan uses '{plan_agg}'. "
                    "Verify the plan is correct."
                )
    return warnings


def _compute_quality_score(
    issues: list[str],
    warnings: list[str],
    row_count: int,
) -> float:
    """
    Heuristic quality score 0-1.
    Blocking issues heavily penalise. Warnings penalise lightly.
    """
    score = 1.0
    score -= len(issues)   * 0.4
    score -= len(warnings) * 0.1
    if row_count < 3:
        score -= 0.2
    return round(max(0.0, min(1.0, score)), 2)


# ── public API ────────────────────────────────────────────────────

def validate_result(
    query_intent:     dict[str, Any],
    analysis_plan:    dict[str, Any],
    execution_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate execution result against intent and plan.

    Returns a ValidationReport:
    {
        "valid": bool,
        "issues": list[str],
        "warnings": list[str],
        "corrections": list[str],
        "quality_score": float
    }
    """
    all_issues:   list[str] = []
    all_warnings: list[str] = []
    corrections:  list[str] = []

    # check 1: did execution succeed?
    empty_issues = _check_empty(execution_result)
    all_issues.extend(empty_issues)

    if not all_issues:  # only run further checks if data exists
        # check 2: metric range validation
        range_issues, range_warnings = _check_metric_range(query_intent, execution_result)
        all_issues.extend(range_issues)
        all_warnings.extend(range_warnings)

        # check 3: cardinality
        all_warnings.extend(_check_cardinality(query_intent, execution_result))

        # check 4: all-same values
        all_warnings.extend(_check_single_value(execution_result))

        # check 5: metric mismatch
        all_warnings.extend(_check_metric_mismatch(query_intent, analysis_plan))

    row_count     = execution_result.get("row_count", 0)
    quality_score = _compute_quality_score(all_issues, all_warnings, row_count)
    is_valid      = len(all_issues) == 0 and row_count > 0

    return {
        "valid":         is_valid,
        "issues":        all_issues,
        "warnings":      all_warnings,
        "corrections":   corrections,
        "quality_score": quality_score,
    }