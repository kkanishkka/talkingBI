"""
app/services/plan_refinement.py
══════════════════════════════════════════════════════════════════════
Refinement loop: when ReflectionAgent returns is_retryable=True,
this module attempts up to MAX_RETRIES corrections before giving up.

Strategy:
  1. Extract retry_suggestion from ValidationReport
  2. Rebuild plan with refinement_hint
  3. Re-execute
  4. Re-validate
  5. Return best result (even if quality < 1.0, with warnings attached)

This prevents the silent "empty chart" UX from the original system.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.core.models import (
    AnalysisPlan, ExecutionResult, QueryIntent,
    ValidationReport,
)
from app.services.analysis_planning_agent import build_analysis_plan
from app.services.analysis_executor import execute_plan
from app.services.reflection_agent import validate_result

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


def refine_and_execute(
    intent:          QueryIntent,
    initial_plan:    AnalysisPlan,
    initial_result:  ExecutionResult,
    initial_report:  ValidationReport,
    schema_profile:  dict[str, Any],
    df:              pd.DataFrame,
) -> tuple[ExecutionResult, ValidationReport, list[str]]:
    """
    Attempt plan refinement when initial validation fails.

    Returns:
        (best_result, best_report, refinement_log)
    """
    refinement_log: list[str] = []
    best_result = initial_result
    best_report = initial_report

    for attempt in range(1, MAX_RETRIES + 1):
        if not best_report.is_retryable or best_report.retry_suggestion is None:
            break

        hint = best_report.retry_suggestion
        logger.info(
            "PlanRefinement: attempt %d — %s",
            attempt, hint.get("reason", "unknown reason"),
        )
        refinement_log.append(
            f"Attempt {attempt}: {hint.get('reason', 'refinement applied')}"
        )

        new_plan   = build_analysis_plan(intent, schema_profile, refinement_hint=hint)
        new_result = execute_plan(new_plan, df)
        new_report = validate_result(intent, new_plan, new_result)

        # keep new result if it is better
        if new_report.quality_score > best_report.quality_score:
            best_result = new_result
            best_report = new_report
            refinement_log.append(
                f"  → Improved: quality={new_report.quality_score:.2f}, "
                f"rows={new_result.row_count}"
            )
        else:
            refinement_log.append(
                f"  → No improvement (quality={new_report.quality_score:.2f}). Keeping previous."
            )
            break

    return best_result, best_report, refinement_log