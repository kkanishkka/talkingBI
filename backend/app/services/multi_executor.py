"""
app/services/multi_executor.py
══════════════════════════════════════════════════════════════════════
Multi-Execution Engine

Takes a DashboardPlan and executes every SubPlan + KPI against
a DataFrame, returning a MultiExecutionResult that contains:
  - kpi_results:   scalar values for each KPIDefinition
  - chart_results: ExecutionResult for each SubPlan

This is the fix for "one query → one number".
After this module, the pipeline has N results ready for N VizSpecs.

All execution is deterministic pandas — no LLM.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from app.core.models import (
    AnalysisPlan, ExecutionResult, MetricType,
    PlanOperation, QuestionType, QueryIntent,
)
from app.services.analysis_executor import execute_plan
from app.services.planner import DashboardPlan, KPIDefinition, SubPlan

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Result containers
# ═══════════════════════════════════════════════════════════════════

@dataclass
class KPIResult:
    definition: KPIDefinition
    value:      Optional[float]
    formatted:  str
    success:    bool
    error:      Optional[str] = None


@dataclass
class ChartResult:
    sub_plan:        SubPlan
    execution_result: ExecutionResult
    success:         bool


@dataclass
class MultiExecutionResult:
    kpi_results:   list[KPIResult]   = field(default_factory=list)
    chart_results: list[ChartResult] = field(default_factory=list)
    warnings:      list[str]         = field(default_factory=list)

    @property
    def successful_charts(self) -> list[ChartResult]:
        return [c for c in self.chart_results if c.success and c.execution_result.data]


# ═══════════════════════════════════════════════════════════════════
# KPI execution (scalar aggregation)
# ═══════════════════════════════════════════════════════════════════

def _execute_kpi(kpi: KPIDefinition, df: pd.DataFrame) -> KPIResult:
    """Compute a single scalar KPI from the dataframe."""
    try:
        if kpi.metric == "count" or kpi.target is None:
            value = float(len(df))
        elif kpi.target not in df.columns:
            return KPIResult(
                definition=kpi, value=None, formatted="N/A",
                success=False, error=f"Column '{kpi.target}' not found",
            )
        else:
            series = pd.to_numeric(df[kpi.target], errors="coerce").dropna()
            agg_map = {
                "sum":    series.sum,
                "mean":   series.mean,
                "median": series.median,
                "max":    series.max,
                "min":    series.min,
            }
            fn = agg_map.get(kpi.metric)
            if fn is None:
                return KPIResult(
                    definition=kpi, value=None, formatted="N/A",
                    success=False, error=f"Unknown metric '{kpi.metric}'",
                )
            value = float(fn())

        formatted = _fmt_kpi(value, kpi.metric)
        return KPIResult(definition=kpi, value=value, formatted=formatted, success=True)

    except Exception as exc:
        logger.warning("KPI '%s' failed: %s", kpi.label, exc)
        return KPIResult(definition=kpi, value=None, formatted="N/A",
                         success=False, error=str(exc))


def _fmt_kpi(value: float, metric: str) -> str:
    if metric == "rate":
        return f"{value * 100:.1f}%"
    if metric == "count":
        return f"{int(value):,}"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.2f}"


# ═══════════════════════════════════════════════════════════════════
# SubPlan → AnalysisPlan converter
# ═══════════════════════════════════════════════════════════════════

def _sub_plan_to_analysis_plan(sp: SubPlan, df: pd.DataFrame) -> AnalysisPlan:
    """Convert a SubPlan into the AnalysisPlan shape that execute_plan() expects."""
    ops: list[PlanOperation] = []
    step = 1

    # Filters
    for f in sp.filters:
        ops.append(PlanOperation(
            step=step, op="filter",
            args={"column": f["column"], "operator": f["operator"], "value": f["value"]},
        ))
        step += 1

    # Main aggregation
    if sp.question_type == "trend" and sp.time_column:
        ops.append(PlanOperation(
            step=step, op="time_resample",
            args={
                "date_col": sp.time_column,
                "freq":     sp.time_grain or "M",
                "target":   sp.target,
                "agg_fn":   sp.metric if sp.metric != "rate" else "count",
            },
        ))
        step += 1
        x_field = sp.time_column
    elif sp.dimension:
        agg_args: dict[str, Any] = {
            "group_by": [sp.dimension],
            "target":   sp.target or sp.dimension,
            "agg_fn":   sp.metric,
        }
        if sp.metric == "rate":
            agg_args["rate_value"] = sp.rate_value or "yes"
        ops.append(PlanOperation(step=step, op="groupby_agg", args=agg_args))
        step += 1
        x_field = sp.dimension
    else:
        # Fallback: value_counts on the target column if it's a dimension
        col = sp.target or (df.columns[0] if len(df.columns) else "unknown")
        ops.append(PlanOperation(
            step=step, op="value_counts",
            args={"column": col, "normalize": False},
        ))
        step += 1
        x_field = col

    # Sort
    if sp.question_type in ("ranking", "comparison", "distribution"):
        ops.append(PlanOperation(
            step=step, op="sort",
            args={"by": "value", "ascending": sp.sort_direction == "asc"},
        ))
        step += 1

    # Top-N
    if sp.top_n:
        ops.append(PlanOperation(step=step, op="top_n", args={"n": sp.top_n}))
        step += 1

    metric_label = _metric_label_str(sp.metric, sp.target)
    dim_pretty   = (sp.dimension or "").replace("_", " ").title()
    result_label = f"{metric_label} by {dim_pretty}" if sp.dimension else metric_label

    return AnalysisPlan(
        operations=     ops,
        result_columns= [x_field, "value"],
        x_field=        x_field,
        y_field=        "value",
        metric_label=   metric_label,
        result_label=   result_label,
        formula_spec=   sp.formula,
        confidence=     0.85,
        reasoning=      f"Generated from SubPlan {sp.id}",
    )


def _metric_label_str(metric: str, target: Optional[str]) -> str:
    pretty = (target or "value").replace("_", " ").title()
    return {
        "sum":    f"Total {pretty}",
        "mean":   f"Average {pretty}",
        "count":  "Count",
        "max":    f"Max {pretty}",
        "min":    f"Min {pretty}",
        "median": f"Median {pretty}",
        "rate":   f"{pretty} Rate",
    }.get(metric, f"{metric.title()} {pretty}")


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def execute_dashboard_plan(
    plan: DashboardPlan,
    df:   pd.DataFrame,
) -> MultiExecutionResult:
    """
    Execute every KPI and SubPlan in the DashboardPlan.
    Returns MultiExecutionResult with all computed values.

    For 'analyze sales and profit by category':
      kpi_results:   [Total Sales: 2.1M, Total Profit: 280K]
      chart_results: [Sales by Category (10 rows), Profit by Category (10 rows)]
    """
    result = MultiExecutionResult()

    # ── Execute KPIs ──────────────────────────────────────────────
    for kpi in plan.kpi_definitions:
        kr = _execute_kpi(kpi, df)
        result.kpi_results.append(kr)
        if not kr.success:
            result.warnings.append(f"KPI '{kpi.label}': {kr.error}")
        else:
            logger.debug("KPI '%s' = %s", kpi.label, kr.formatted)

    # ── Execute chart sub-plans ───────────────────────────────────
    for sp in plan.sub_plans:
        try:
            analysis_plan = _sub_plan_to_analysis_plan(sp, df)
            exec_result   = execute_plan(analysis_plan, df)

            success = exec_result.success and bool(exec_result.data)
            result.chart_results.append(ChartResult(
                sub_plan=sp,
                execution_result=exec_result,
                success=success,
            ))
            if not success:
                err = exec_result.error or "no data returned"
                result.warnings.append(f"Chart '{sp.label}': {err}")
                logger.warning("SubPlan '%s' failed: %s", sp.id, err)
            else:
                logger.debug(
                    "SubPlan '%s' → %d rows", sp.id, exec_result.row_count
                )
        except Exception as exc:
            logger.error("SubPlan '%s' exception: %s", sp.id, exc)
            result.warnings.append(f"Chart '{sp.label}': {exc}")

    logger.info(
        "execute_dashboard_plan: %d/%d KPIs ok, %d/%d charts ok",
        sum(1 for k in result.kpi_results if k.success), len(result.kpi_results),
        len(result.successful_charts), len(result.chart_results),
    )
    return result