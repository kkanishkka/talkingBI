"""
app/layers/reasoning/reflection.py
══════════════════════════════════════════════════════════════════════
Reflection / Validator — moved from services/reflection_agent.py.
Logic unchanged. Import paths updated.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.models import (
    AnalysisPlan, ExecutionResult, MetricType,
    QueryIntent, ValidationReport,
)

import logging
logger = logging.getLogger(__name__)


def _numeric_values(result: ExecutionResult) -> list[float]:
    y = result.y_field
    vals = []
    for row in result.data:
        v = row.get(y)
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    return vals


def validate_result(
    intent:  QueryIntent,
    plan:    AnalysisPlan,
    result:  ExecutionResult,
) -> ValidationReport:
    issues:           list[str] = []
    warnings:         list[str] = []
    corrections:      list[str] = []
    retry_suggestion: Optional[dict[str, Any]] = None
    is_retryable = False

    if not result.success:
        issues.append(f"Execution failed: {result.error or 'unknown error'}")
        return ValidationReport(
            valid=False, issues=issues, warnings=warnings,
            corrections=corrections, quality_score=0.0, is_retryable=False,
        )

    if not result.data:
        issues.append("Execution returned no rows.")
        is_retryable = True
        retry_suggestion = {"change_metric": "count", "reason": "No data returned — trying count instead"}
        return ValidationReport(
            valid=False, issues=issues, warnings=warnings,
            corrections=corrections, quality_score=0.0,
            is_retryable=is_retryable, retry_suggestion=retry_suggestion,
        )

    vals = _numeric_values(result)

    if intent.metric == MetricType.rate and vals:
        max_val = max(vals)
        if max_val > 1.0:
            issues.append(
                f"Rate values exceed 1.0 (max={max_val:.3f}). "
                "Count was likely computed instead of rate."
            )
            is_retryable = True
            retry_suggestion = {
                "change_metric": "count",
                "reason": f"Rate > 1.0 (max={max_val:.3f}) — switching to count",
            }
        if vals and max(vals) < 0.001:
            warnings.append(
                f"Rate is extremely small (max={max(vals):.5f}). "
                "Verify the positive class value is correct."
            )

    if intent.metric in (MetricType.count, MetricType.sum) and vals:
        if min(vals) < 0:
            issues.append(f"Negative {intent.metric} values detected — data issue.")

    if result.row_count == 1:
        warnings.append(
            "Result has only 1 row. Check that groupby column has multiple categories."
        )
    elif result.row_count > 50:
        warnings.append(
            f"Result has {result.row_count} rows. "
            "Consider adding top_n (e.g. 10–15) for a readable chart."
        )

    if vals and len(set(round(v, 6) for v in vals)) == 1:
        warnings.append(
            f"All result rows have the same value ({vals[0]}). "
            "This chart will show no variation."
        )

    for op in plan.operations:
        if op.op == "groupby_agg":
            plan_agg = op.args.get("agg_fn")
            if plan_agg and plan_agg != str(intent.metric):
                warnings.append(
                    f"Metric mismatch: intent='{intent.metric}' but plan uses '{plan_agg}'."
                )

    input_rows = result.intermediate_counts.get("input", 0)
    if input_rows > 0:
        final_rows = max(
            (v for k, v in result.intermediate_counts.items()
             if "groupby" in k or "resample" in k or "value_counts" in k),
            default=result.row_count,
        )
        if final_rows < input_rows * 0.05:
            warnings.append(
                f"Filter reduced rows from {input_rows:,} to {final_rows:,} "
                f"({100*final_rows/input_rows:.1f}% remaining). "
                "Verify filter conditions are correct."
            )

    score = 1.0 - len(issues) * 0.4 - len(warnings) * 0.08
    if result.row_count < 3:
        score -= 0.15
    score = round(max(0.0, min(1.0, score)), 2)

    return ValidationReport(
        valid=           len(issues) == 0 and result.row_count > 0,
        issues=          issues,
        warnings=        warnings,
        corrections=     corrections,
        quality_score=   score,
        is_retryable=    is_retryable,
        retry_suggestion=retry_suggestion,
    )
