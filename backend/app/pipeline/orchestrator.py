"""
app/pipeline/orchestrator.py  — v4 (multi-chart pipeline)
══════════════════════════════════════════════════════════════════════
Pipeline Orchestrator — upgraded to support multi-chart dashboards.

New flow vs v3:
  OLD: understand → plan → execute (1×) → viz (1×) → narrate
  NEW: understand → PLANNER → execute (N×) → charts (N×) → insights

The key new steps are:
  step_plan_dashboard()  — calls planner.plan_dashboard()
  step_multi_execute()   — calls multi_executor.execute_dashboard_plan()
  step_generate_charts() — calls chart_generator.generate_charts()
  step_result_insights() — calls result_insight_engine.generate_result_insights()

Old single-chart path is preserved as fallback (step_build_vizs_single)
for queries that are genuinely single-metric (e.g. "what is total sales?").

Entry points (unchanged signatures):
  run_pipeline(file, prompt, session_id)
  run_pipeline_from_dataframe(df, source_name, prompt, session_id)
  run_pipeline_from_text(prompt, session_id)
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import AmbiguityError
from app.core.models import QuestionType, VizSpec
from app.core.session_store import session_store

from app.layers.ingestion.loader import load_dataframe, validate_dataframe
from app.layers.semantic.schema_profiler import profile_dataframe, build_schema_context
from app.layers.reasoning.query_understanding import understand_query
from app.layers.reasoning.ambiguity_resolver import check_for_ambiguity
from app.layers.reasoning.analysis_planner import build_analysis_plan
from app.layers.reasoning.analysis_executor import execute_plan
from app.layers.reasoning.reflection import validate_result
from app.layers.reasoning.plan_refinement import refine_and_execute
from app.layers.validation.confidence_scorer import compute_confidence
from app.layers.presentation.viz_reasoner import (
    reason_visualization, build_dashboard_layouts,
    filter_vizs_by_intent, is_kpi_result,
)
from app.layers.presentation.insight_narrator import narrate_insights, build_assumption_block
from app.layers.presentation.insight_engine import generate_dataset_insights
from app.layers.presentation.coverage_engine import compute_kpi_coverage
from app.layers.presentation.dashboard_composer import (
    compose_dashboard, generate_followup_suggestions,
)

# ── NEW multi-chart modules ────────────────────────────────────────
from app.services.planner import plan_dashboard, DashboardPlan
from app.services.multi_executor import execute_dashboard_plan, MultiExecutionResult
from app.services.chart_generator import generate_charts
from app.services.result_insight_engine import generate_result_insights

from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — existing step implementations (unchanged)
# ═══════════════════════════════════════════════════════════════════

def step_ingest(ctx: PipelineContext, file: UploadFile) -> None:
    df, filename = load_dataframe(file)
    warnings = validate_dataframe(df, filename)
    ctx.df       = df
    ctx.filename = filename
    ctx.add_warnings(warnings)
    logger.info("[%s] Ingested '%s': %d×%d",
                ctx.request_id, filename, len(df), len(df.columns))


def step_ingest_dataframe(ctx: PipelineContext, df: pd.DataFrame, source_name: str) -> None:
    warnings = validate_dataframe(df, source_name)
    ctx.df       = df
    ctx.filename = source_name
    ctx.add_warnings(warnings)
    logger.info("[%s] Ingested dataframe '%s': %d×%d",
                ctx.request_id, source_name, len(df), len(df.columns))


def step_profile(ctx: PipelineContext) -> None:
    assert ctx.df is not None
    ctx.schema_profile = profile_dataframe(ctx.df)
    ctx.schema_context = build_schema_context(ctx.schema_profile)
    logger.info("[%s] Profiled: %d cols", ctx.request_id, len(ctx.schema_profile["columns"]))


def step_session_load(ctx: PipelineContext) -> None:
    session_ctx, is_new = session_store.get_or_create(ctx.session_id)
    ctx.session_id  = session_ctx.session_id
    ctx.session_ctx = session_ctx

    if ctx.schema_context:
        col_names = ctx.schema_profile["dataset_summary"]["column_names"]
        row_count = ctx.schema_profile["dataset_summary"]["rows"]
        session_store.set_schema(
            ctx.session_id, ctx.schema_context,
            col_names, row_count,
            schema_profile=ctx.schema_profile,
        )

    if is_new:
        logger.info("[%s] New session: %s", ctx.request_id, ctx.session_id[:8])
    else:
        logger.info("[%s] Resumed session: %s (%d turns)",
                    ctx.request_id, ctx.session_id[:8], len(session_ctx.conversation_turns))


def step_query_understand(ctx: PipelineContext) -> None:
    assert ctx.schema_profile is not None
    ctx.intent = understand_query(ctx.prompt, ctx.schema_profile, ctx.session_ctx)
    logger.info("[%s] Intent: type=%s metric=%s dim=%s target=%s",
                ctx.request_id, ctx.intent.question_type, ctx.intent.metric,
                ctx.intent.primary_dimension, ctx.intent.target_variable)


def step_ambiguity_check(ctx: PipelineContext) -> None:
    assert ctx.intent is not None and ctx.schema_profile is not None
    signal = check_for_ambiguity(ctx.prompt, ctx.intent, ctx.schema_profile)
    ctx.ambiguity_signal = signal
    if signal.is_ambiguous:
        raise AmbiguityError({
            "question": signal.clarification_question,
            "reason":   signal.reason,
            "options":  signal.options,
        })


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — NEW: dashboard planner + multi-executor steps
# ═══════════════════════════════════════════════════════════════════

def step_plan_dashboard(ctx: PipelineContext) -> None:
    """
    NEW: Replace single-plan step with multi-chart planner.
    Sets ctx.dashboard_plan (DashboardPlan).
    Also keeps ctx.plan populated for backward-compat (uses first sub-plan).
    """
    assert ctx.intent is not None and ctx.schema_profile is not None

    ctx.dashboard_plan = plan_dashboard(ctx.intent, ctx.schema_profile)

    logger.info(
        "[%s] DashboardPlan: %d KPIs, %d charts, is_dashboard=%s",
        ctx.request_id,
        len(ctx.dashboard_plan.kpi_definitions),
        len(ctx.dashboard_plan.sub_plans),
        ctx.dashboard_plan.is_dashboard,
    )

    # Backward-compat: build a single AnalysisPlan from intent for
    # validation / confidence scoring (which still expect ctx.plan)
    ctx.plan = build_analysis_plan(ctx.intent, ctx.schema_profile)


def step_execute_single(ctx: PipelineContext) -> None:
    """
    Backward-compat single-execution pass.
    Used for validation + confidence scoring only.
    """
    assert ctx.plan is not None and ctx.df is not None and ctx.intent is not None
    ctx.result     = execute_plan(ctx.plan, ctx.df)
    ctx.validation = validate_result(ctx.intent, ctx.plan, ctx.result)

    if ctx.result.sample_warning:
        ctx.add_warning(ctx.result.sample_warning)

    if not ctx.validation.valid and ctx.validation.is_retryable:
        ctx.result, ctx.validation, ctx.refinement_log = refine_and_execute(
            ctx.intent, ctx.plan, ctx.result, ctx.validation,
            ctx.schema_profile, ctx.df,
        )
        ctx.add_warnings(ctx.refinement_log)

    ctx.add_warnings(ctx.validation.issues)
    ctx.add_warnings(ctx.validation.warnings)


def step_multi_execute(ctx: PipelineContext) -> None:
    """
    NEW: Execute every sub-plan in the DashboardPlan.
    Sets ctx.multi_result (MultiExecutionResult).
    """
    assert ctx.dashboard_plan is not None and ctx.df is not None
    ctx.multi_result = execute_dashboard_plan(ctx.dashboard_plan, ctx.df)
    ctx.add_warnings(ctx.multi_result.warnings)
    logger.info(
        "[%s] MultiExecute: %d KPI ok, %d charts ok",
        ctx.request_id,
        sum(1 for k in ctx.multi_result.kpi_results if k.success),
        len(ctx.multi_result.successful_charts),
    )


def step_score_confidence(ctx: PipelineContext) -> None:
    assert all(x is not None for x in [ctx.intent, ctx.plan, ctx.result, ctx.schema_profile])
    ctx.confidence = compute_confidence(ctx.intent, ctx.plan, ctx.result, ctx.schema_profile)
    logger.info("[%s] Confidence: %.3f (%s)",
                ctx.request_id, ctx.confidence.overall_confidence, ctx.confidence.tier)


def step_build_vizs(ctx: PipelineContext) -> None:
    """
    NEW: Generate all VizSpecs from multi-execution results.
    Falls back to old single-viz path if multi-execution produced nothing.
    """
    assert ctx.multi_result is not None and ctx.schema_profile is not None

    # Primary path: multi-chart
    ctx.all_vizs = generate_charts(ctx.multi_result, max_charts=6)
    ctx.is_kpi_only = (
        len(ctx.all_vizs) > 0
        and all(v.get("chart_type") == "kpi_card" for v in ctx.all_vizs)
    )

    if ctx.all_vizs:
        ctx.primary_viz = ctx.all_vizs[0]
        logger.info("[%s] Generated %d vizs (multi-chart path)", ctx.request_id, len(ctx.all_vizs))
        return

    # Fallback: old single-viz path
    logger.warning("[%s] Multi-chart produced 0 vizs — falling back to single-chart", ctx.request_id)
    if ctx.result and ctx.intent and ctx.validation and ctx.validation.valid and ctx.result.data:
        pv = reason_visualization(ctx.intent, ctx.result, ctx.schema_profile, is_primary=True)
        ctx.primary_viz = pv.dict()
        ctx.all_vizs = [ctx.primary_viz]
        ctx.is_kpi_only = is_kpi_result(ctx.result)
    else:
        ctx.all_vizs = []


def step_result_insights(ctx: PipelineContext) -> None:
    """
    NEW: Generate insights from computed values (not just schema).
    Sets ctx.result_insights (list of insight dicts).
    """
    assert ctx.dashboard_plan is not None and ctx.multi_result is not None
    ctx.result_insights = generate_result_insights(ctx.dashboard_plan, ctx.multi_result)
    logger.info("[%s] Generated %d result insights", ctx.request_id, len(ctx.result_insights))


def step_narrate(ctx: PipelineContext) -> None:
    assert ctx.intent is not None and ctx.result is not None
    if ctx.validation and ctx.validation.valid and ctx.result.data:
        ir = narrate_insights(ctx.intent, ctx.result, ctx.primary_viz)
        ctx.insight_report = ir.dict()


def step_build_assumptions(ctx: PipelineContext) -> None:
    assert ctx.intent is not None and ctx.plan is not None
    ctx.assumption_block = build_assumption_block(ctx.intent, ctx.plan.formula_spec)


def step_compute_coverage(ctx: PipelineContext) -> None:
    assert ctx.intent is not None
    ctx.kpi_coverage = compute_kpi_coverage(
        intent_kpis=    ctx.intent.requested_kpis,
        viz_specs=      ctx.all_vizs,
        schema_profile= ctx.schema_profile,
    ).dict()


def step_build_layouts(ctx: PipelineContext) -> None:
    if ctx.is_kpi_only and not ctx.multi_result.successful_charts:
        ctx.layouts = [{
            "layout_id":   "kpi",
            "layout_name": "KPI View",
            "description": "KPI metrics.",
            "cells": [{"viz_index": i, "col_start": 1 + (i % 2) * 6,
                        "col_span": 6, "row_span": 1}
                       for i in range(min(4, len(ctx.all_vizs)))],
        }]
        return

    viz_spec_objs = []
    for v in ctx.all_vizs:
        try:
            viz_spec_objs.append(VizSpec(**v))
        except Exception:
            pass
    ctx.layouts = [l.dict() for l in build_dashboard_layouts(viz_spec_objs)]


def step_dataset_insights(ctx: PipelineContext) -> None:
    assert ctx.schema_profile is not None
    ctx.dataset_output = generate_dataset_insights(
        ctx.schema_profile,
        {"raw_prompt": ctx.prompt, "business_goal": ctx.prompt},
    )


def step_session_save(ctx: PipelineContext) -> None:
    if ctx.intent and ctx.result and ctx.session_id:
        session_store.record_turn(
            session_id= ctx.session_id,
            prompt=     ctx.prompt,
            intent=     ctx.intent,
            result=     ctx.result,
        )
        refreshed = session_store.get(ctx.session_id)
        if refreshed and ctx.schema_profile:
            refreshed.schema_profile_cache = ctx.schema_profile


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — response assembly (updated)
# ═══════════════════════════════════════════════════════════════════

def _build_kpi_cards(ctx: PipelineContext) -> list[dict]:
    """Serialize KPI results for the response."""
    if not ctx.multi_result:
        return []
    return [
        {
            "label":     k.definition.label,
            "value":     k.value,
            "formatted": k.formatted,
            "formula":   k.definition.formula,
            "success":   k.success,
        }
        for k in ctx.multi_result.kpi_results
    ]


def _build_executed_query(ctx: PipelineContext) -> dict[str, Any]:
    explanation = ""
    if ctx.intent and ctx.intent.assumptions:
        first = ctx.intent.assumptions[0]
        if first.startswith("I "):
            explanation = first

    filters = []
    if ctx.intent:
        for f in ctx.intent.filters:
            filters.append(f.dict() if hasattr(f, "dict") else {
                "column": getattr(f, "column", ""),
                "operator": getattr(f, "operator", "=="),
                "value": getattr(f, "value", None),
            })

    ops = []
    if ctx.plan:
        for op in ctx.plan.operations:
            ops.append(op.dict() if hasattr(op, "dict") else {
                "step": getattr(op, "step", None),
                "op":   getattr(op, "op", ""),
                "args": getattr(op, "args", {}),
            })

    plan_summary = ""
    if ctx.dashboard_plan:
        plan_summary = ctx.dashboard_plan.query_summary

    return {
        "query_type":          "pandas_multi",
        "metric":              str(ctx.intent.metric) if ctx.intent else "",
        "question_type":       str(ctx.intent.question_type) if ctx.intent else "",
        "dimension":           ctx.intent.primary_dimension if ctx.intent else None,
        "secondary_dimension": ctx.intent.secondary_dimension if ctx.intent else None,
        "target_variable":     ctx.intent.target_variable if ctx.intent else None,
        "filters":             filters,
        "formula":             ctx.plan.formula_spec if ctx.plan else "",
        "operations":          ops,
        "row_count":           ctx.result.row_count if ctx.result else 0,
        "is_kpi_only":         getattr(ctx, "is_kpi_only", False),
        "explanation":         explanation,
        "dashboard_plan":      plan_summary,
        "chart_count":         len(ctx.all_vizs),
    }


def step_assemble(ctx: PipelineContext) -> dict:
    assert ctx.intent is not None

    followup_suggestions = []
    try:
        if ctx.result and ctx.schema_profile:
            followup_suggestions = generate_followup_suggestions(
                ctx.intent, ctx.result, ctx.schema_profile
            )
    except Exception:
        pass

    executed_query = _build_executed_query(ctx)
    explanation    = executed_query.get("explanation", "")

    # Build assistant message: headline + explanation
    assistant_message = ""
    if ctx.insight_report and ctx.insight_report.get("headline"):
        assistant_message = ctx.insight_report["headline"]
    elif ctx.result_insights:
        first = ctx.result_insights[0]
        assistant_message = first.get("insight_text", "")[:200]
    if explanation and assistant_message and explanation not in assistant_message:
        assistant_message = f"{assistant_message}\n\n*{explanation}*"
    elif explanation:
        assistant_message = explanation
    if not assistant_message:
        assistant_message = f"Dashboard generated in {ctx.elapsed}s."

    # Merge schema insights + result insights
    all_insights = (getattr(ctx, "result_insights", None) or []) + \
                   (ctx.dataset_output.get("insights", []) if ctx.dataset_output else [])

    return {
        "message":           f"Dashboard generated in {ctx.elapsed}s.",
        "assistant_message": assistant_message,
        "session_id":        ctx.session_id,
        "request_id":        ctx.request_id,
        "is_kpi_only":       getattr(ctx, "is_kpi_only", False),

        # ── NEW: structured KPI cards ─────────────────────────────
        "kpi_cards": _build_kpi_cards(ctx),

        "analysis_report": {
            "query_intent":    ctx.intent.dict(),
            "plan_summary": {
                "formula_spec":     ctx.plan.formula_spec if ctx.plan else "",
                "result_label":     ctx.plan.result_label if ctx.plan else "",
                "metric_label":     ctx.plan.metric_label if ctx.plan else "",
                "reasoning":        ctx.plan.reasoning    if ctx.plan else "",
                "confidence":       ctx.plan.confidence   if ctx.plan else 0.0,
                "operations_count": len(ctx.plan.operations) if ctx.plan else 0,
                "dashboard_plan":   ctx.dashboard_plan.query_summary if ctx.dashboard_plan else "",
                "sub_plan_count":   len(ctx.dashboard_plan.sub_plans) if ctx.dashboard_plan else 0,
            },
            "validation":         ctx.validation.dict() if ctx.validation else {},
            "insight_report":     ctx.insight_report,
            "confidence":         ctx.confidence.factors      if ctx.confidence else {},
            "confidence_tier":    ctx.confidence.tier         if ctx.confidence else "unknown",
            "confidence_message": ctx.confidence.user_message if ctx.confidence else "",
        },

        "executed_query":  executed_query,
        "assumptions":     ctx.assumption_block.dict() if ctx.assumption_block else {},
        "kpi_coverage":    ctx.kpi_coverage or {},

        "visualizations": ctx.all_vizs,
        "layouts":        ctx.layouts,

        "executive_summary": ctx.dataset_output.get("executive_summary", []) if ctx.dataset_output else [],
        "dataset_insights":  all_insights[:8],
        "dataset_profile":   _build_dataset_profile(ctx),

        "follow_up_suggestions": followup_suggestions,
        "warnings":              ctx.warnings,
    }


def _build_dataset_profile(ctx: PipelineContext) -> dict:
    if not ctx.schema_profile:
        return {}
    summary = ctx.schema_profile["dataset_summary"]
    return {
        "rows":           summary["rows"],
        "columns":        summary["columns"],
        "column_names":   summary["column_names"],
        "column_details": [
            {
                "name":            c["name"],
                "dtype":           c["dtype"],
                "role":            c["role"],
                "semantic_hint":   c.get("semantic_hint", "none"),
                "unique_count":    c["unique_count"],
                "null_percentage": c["null_percentage"],
            }
            for c in ctx.schema_profile["columns"]
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# SECTION 4 — shared step runner (updated pipeline order)
# ═══════════════════════════════════════════════════════════════════

def _run_pipeline_steps(ctx: PipelineContext) -> dict:
    step_profile(ctx)
    step_session_load(ctx)
    step_query_understand(ctx)
    step_ambiguity_check(ctx)

    # ── NEW multi-chart planning ──────────────────────────────────
    step_plan_dashboard(ctx)        # builds DashboardPlan + ctx.plan
    step_execute_single(ctx)        # single exec for validation/confidence
    step_multi_execute(ctx)         # executes all sub-plans
    # ─────────────────────────────────────────────────────────────

    step_score_confidence(ctx)
    step_build_vizs(ctx)            # uses multi_result → all_vizs
    step_result_insights(ctx)       # NEW: compute-value insights
    step_narrate(ctx)               # narrative for primary result
    step_build_assumptions(ctx)
    step_compute_coverage(ctx)
    step_build_layouts(ctx)
    step_dataset_insights(ctx)
    step_session_save(ctx)

    response = step_assemble(ctx)
    logger.info(
        "[%s] Pipeline done in %.2fs — %d vizs, %d KPIs, %d insights, kpi_only=%s",
        ctx.request_id, ctx.elapsed,
        len(ctx.all_vizs),
        len(ctx.multi_result.kpi_results) if ctx.multi_result else 0,
        len(getattr(ctx, "result_insights", [])),
        getattr(ctx, "is_kpi_only", False),
    )
    return response


# ═══════════════════════════════════════════════════════════════════
# SECTION 5 — public entry points (unchanged signatures)
# ═══════════════════════════════════════════════════════════════════

def run_pipeline(file: UploadFile, prompt: str, session_id: str) -> dict:
    ctx = PipelineContext(prompt=prompt, session_id=session_id)
    step_ingest(ctx, file)
    return _run_pipeline_steps(ctx)


def run_pipeline_from_dataframe(
    df:          pd.DataFrame,
    source_name: str,
    prompt:      str,
    session_id:  str,
) -> dict:
    ctx = PipelineContext(prompt=prompt, session_id=session_id)
    step_ingest_dataframe(ctx, df, source_name)
    return _run_pipeline_steps(ctx)


def run_pipeline_from_text(prompt: str, session_id: str) -> dict:
    from fastapi import HTTPException
    from app.layers.ingestion.datasources.supabase import SupabaseDataSource

    connection_string = session_store.get_connection_string(session_id)
    selected_table    = session_store.get_selected_table(session_id)

    if not connection_string:
        raise HTTPException(status_code=404, detail="Session not found or database not connected.")
    if not selected_table:
        raise HTTPException(status_code=400, detail="No table selected for this session.")

    ds = SupabaseDataSource(connection_string)
    df = ds.load_dataframe(selected_table, limit=50000)
    return run_pipeline_from_dataframe(
        df=df, source_name=selected_table,
        prompt=prompt, session_id=session_id,
    )