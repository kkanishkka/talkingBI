"""
app/services/reflection_agent.py
══════════════════════════════════════════════════════════════════════
Agent 4: Reflection / Validator

Validates ExecutionResult against QueryIntent + AnalysisPlan.
When a problem is found, produces a retry_suggestion so the
PlanRefinement loop can attempt a fix before giving up.

Checks:
  1. Execution success + non-empty data
  2. Rate values in [0,1]
  3. Count values ≥ 0
  4. Cardinality: warn if 1 row or >50 rows
  5. All-same values (useless chart)
  6. Metric mismatch between intent and plan ops
  7. Aggressive filter: warn if rows dropped >90%
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.models import (
    AnalysisPlan, ExecutionResult, MetricType, QueryIntent,
    ValidationReport,
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
    intent:   QueryIntent,
    plan:     AnalysisPlan,
    result:   ExecutionResult,
) -> ValidationReport:
    issues:      list[str] = []
    warnings:    list[str] = []
    corrections: list[str] = []
    retry_suggestion: Optional[dict[str, Any]] = None
    is_retryable = False

    # ── 1. Execution success ──────────────────────────────────────
    if not result.success:
        issues.append(f"Execution failed: {result.error or 'unknown error'}")
        return ValidationReport(
            valid=False, issues=issues, warnings=warnings,
            corrections=corrections, quality_score=0.0,
            is_retryable=False,
        )

    if not result.data:
        issues.append("Execution returned no rows.")
        is_retryable = True
        retry_suggestion = {"change_metric": "count",
                            "reason": "No data returned — trying count instead"}
        return ValidationReport(
            valid=False, issues=issues, warnings=warnings,
            corrections=corrections, quality_score=0.0,
            is_retryable=is_retryable, retry_suggestion=retry_suggestion,
        )

    vals = _numeric_values(result)

    # ── 2. Rate range check ───────────────────────────────────────
    if intent.metric == MetricType.rate and vals:
        max_val = max(vals)
        if max_val > 1.0:
            issues.append(
                f"Rate values exceed 1.0 (max={max_val:.3f}). "
                "Count was likely computed instead of rate. "
                "Verify rate_value matches the positive class in your data."
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

    # ── 3. Count/sum negativity ───────────────────────────────────
    if intent.metric in (MetricType.count, MetricType.sum) and vals:
        if min(vals) < 0:
            issues.append(f"Negative {intent.metric} values detected — data issue.")

    # ── 4. Cardinality ────────────────────────────────────────────
    if result.row_count == 1:
        warnings.append(
            "Result has only 1 row. Check that groupby column has multiple categories, "
            "or that a filter didn't collapse the data."
        )
    elif result.row_count > 50:
        warnings.append(
            f"Result has {result.row_count} rows. "
            "Consider adding top_n (e.g. 10–15) for a readable chart."
        )

    # ── 5. All-same values ────────────────────────────────────────
    if vals and len(set(round(v, 6) for v in vals)) == 1:
        warnings.append(
            f"All result rows have the same value ({vals[0]}). "
            "This chart will show no variation."
        )

    # ── 6. Metric mismatch ────────────────────────────────────────
    for op in plan.operations:
        if op.op == "groupby_agg":
            plan_agg = op.args.get("agg_fn")
            if plan_agg and plan_agg != str(intent.metric):
                warnings.append(
                    f"Metric mismatch: intent='{intent.metric}' but plan uses '{plan_agg}'. "
                    "Verify the plan is correct."
                )

    # ── 7. Aggressive filter check ────────────────────────────────
    input_rows = result.intermediate_counts.get("input", 0)
    if input_rows > 0:
        final_rows_before_sort = max(
            (v for k, v in result.intermediate_counts.items()
             if "groupby" in k or "resample" in k or "value_counts" in k),
            default=result.row_count,
        )
        if final_rows_before_sort < input_rows * 0.05:
            warnings.append(
                f"Filter reduced rows from {input_rows:,} to {final_rows_before_sort:,} "
                f"({100*final_rows_before_sort/input_rows:.1f}% remaining). "
                "Verify filter conditions are correct."
            )

    # ── quality score ─────────────────────────────────────────────
    score = 1.0 - len(issues) * 0.4 - len(warnings) * 0.08
    if result.row_count < 3:
        score -= 0.15
    score = round(max(0.0, min(1.0, score)), 2)

    return ValidationReport(
        valid=          len(issues) == 0 and result.row_count > 0,
        issues=         issues,
        warnings=       warnings,
        corrections=    corrections,
        quality_score=  score,
        is_retryable=   is_retryable,
        retry_suggestion= retry_suggestion,
    )