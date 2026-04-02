"""
app/layers/reasoning/plan_refinement.py
══════════════════════════════════════════════════════════════════════
Plan Refinement — moved from services/plan_refinement.py.
Logic unchanged. Import paths updated to layered structure.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.models import AnalysisPlan, ExecutionResult, QueryIntent, ValidationReport
from app.layers.reasoning.analysis_planner import build_analysis_plan
from app.layers.reasoning.analysis_executor import execute_plan
from app.layers.reasoning.reflection import validate_result

logger = logging.getLogger(__name__)


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
    Returns (best_result, best_report, refinement_log).
    """
    refinement_log: list[str] = []
    best_result = initial_result
    best_report = initial_report

    for attempt in range(1, settings.max_retries + 1):
        if not best_report.is_retryable or best_report.retry_suggestion is None:
            break

        hint = best_report.retry_suggestion
        logger.info("PlanRefinement: attempt %d — %s", attempt, hint.get("reason", ""))
        refinement_log.append(f"Attempt {attempt}: {hint.get('reason', 'refinement applied')}")

        new_plan   = build_analysis_plan(intent, schema_profile, refinement_hint=hint)
        new_result = execute_plan(new_plan, df)
        new_report = validate_result(intent, new_plan, new_result)

        if new_report.quality_score > best_report.quality_score:
            best_result = new_result
            best_report = new_report
            refinement_log.append(
                f"  → Improved: quality={new_report.quality_score:.2f}, rows={new_result.row_count}"
            )
        else:
            refinement_log.append(
                f"  → No improvement (quality={new_report.quality_score:.2f}). Keeping previous."
            )
            break

    return best_result, best_report, refinement_log
