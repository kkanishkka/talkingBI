"""
app/pipeline/orchestrator.py
══════════════════════════════════════════════════════════════════════
Pipeline Orchestrator — replaces the 200-line function in dashboard.py.

Each pipeline step is a discrete function that reads/writes PipelineContext.
The orchestrator calls them in sequence and handles errors at each boundary.

Pipeline steps:
  1.  ingest           — load DataFrame, validate
  2.  profile          — schema profiling + semantic enrichment
  3.  session_load     — load/create session context
  4.  query_understand — prompt → QueryIntent (session-aware)
  5.  ambiguity_check  — detect and surface ambiguous queries
  6.  plan             — QueryIntent → AnalysisPlan
  7.  execute          — AnalysisPlan → ExecutionResult (deterministic)
  8.  reflect          — validate result, retry if needed
  9.  score_confidence — multi-factor confidence scoring
  10. build_vizs       — ExecutionResult → VizSpec(s)
  11. narrate          — ExecutionResult → InsightReport
  12. build_assumptions — intent + plan → AssumptionBlock
  13. compute_coverage — KPI coverage (semantic)
  14. build_layouts    — VizSpec[] → DashboardLayout[]
  15. dataset_insights — schema → structural insights + exec summary
  16. session_save     — persist turn to session store
  17. assemble         — build final response dict
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import AmbiguityError, IngestionError
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
from app.layers.presentation.viz_reasoner import reason_visualization, build_dashboard_layouts
from app.layers.presentation.insight_narrator import narrate_insights, build_assumption_block
from app.layers.presentation.insight_engine import generate_dataset_insights
from app.layers.presentation.coverage_engine import compute_kpi_coverage
from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


# ── Step implementations ──────────────────────────────────────────

def step_ingest(ctx: PipelineContext, file: UploadFile) -> None:
    df, filename = load_dataframe(file)
    warnings = validate_dataframe(df, filename)
    ctx.df       = df
    ctx.filename = filename
    ctx.add_warnings(warnings)
    logger.info("[%s] Ingested '%s': %d×%d", ctx.request_id, filename, len(df), len(df.columns))


def step_profile(ctx: PipelineContext) -> None:
    assert ctx.df is not None
    ctx.schema_profile  = profile_dataframe(ctx.df)
    ctx.schema_context  = build_schema_context(ctx.schema_profile)
    logger.info("[%s] Schema profiled: %d cols", ctx.request_id, len(ctx.schema_profile["columns"]))


def step_session_load(ctx: PipelineContext) -> None:
    session_ctx, is_new = session_store.get_or_create(ctx.session_id)
    ctx.session_id  = session_ctx.session_id
    ctx.session_ctx = session_ctx

    # Update session with fresh schema
    if ctx.schema_context:
        col_names = ctx.schema_profile["dataset_summary"]["column_names"]
        row_count = ctx.schema_profile["dataset_summary"]["rows"]
        session_store.set_schema(ctx.session_id, ctx.schema_context, col_names, row_count)

    if is_new:
        logger.info("[%s] New session created: %s", ctx.request_id, ctx.session_id[:8])
    else:
        turns = len(session_ctx.conversation_turns)
        logger.info("[%s] Session resumed: %s (%d turns)", ctx.request_id, ctx.session_id[:8], turns)


def step_query_understand(ctx: PipelineContext) -> None:
    assert ctx.schema_profile is not None
    ctx.intent = understand_query(ctx.prompt, ctx.schema_profile, ctx.session_ctx)
    logger.info(
        "[%s] Intent: type=%s metric=%s dim=%s",
        ctx.request_id, ctx.intent.question_type,
        ctx.intent.metric, ctx.intent.primary_dimension,
    )


def step_ambiguity_check(ctx: PipelineContext) -> None:
    assert ctx.intent is not None and ctx.schema_profile is not None
    signal = check_for_ambiguity(ctx.prompt, ctx.intent, ctx.schema_profile)
    ctx.ambiguity_signal = signal
    if signal.is_ambiguous:
        logger.info("[%s] Ambiguity detected: %s", ctx.request_id, signal.reason)
        raise AmbiguityError({
            "question":         signal.clarification_question,
            "reason":           signal.reason,
            "options":          signal.options,
            "partial_intent":   signal.partial_intent,
        })


def step_plan(ctx: PipelineContext) -> None:
    assert ctx.intent is not None and ctx.schema_profile is not None
    ctx.plan = build_analysis_plan(ctx.intent, ctx.schema_profile)
    logger.info("[%s] Plan: %d ops, confidence=%.2f", ctx.request_id,
                len(ctx.plan.operations), ctx.plan.confidence)


def step_execute_and_reflect(ctx: PipelineContext) -> None:
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
    logger.info("[%s] Execution: rows=%d valid=%s quality=%.2f",
                ctx.request_id, ctx.result.row_count,
                ctx.validation.valid, ctx.validation.quality_score)


def step_score_confidence(ctx: PipelineContext) -> None:
    assert all(x is not None for x in [ctx.intent, ctx.plan, ctx.result, ctx.schema_profile])
    ctx.confidence = compute_confidence(ctx.intent, ctx.plan, ctx.result, ctx.schema_profile)
    logger.info("[%s] Confidence: %.3f (%s)", ctx.request_id,
                ctx.confidence.overall_confidence, ctx.confidence.tier)


def step_build_vizs(ctx: PipelineContext) -> None:
    assert ctx.intent is not None and ctx.result is not None and ctx.schema_profile is not None
    is_overview = str(ctx.intent.question_type) == QuestionType.overview

    # Primary viz
    if ctx.validation and ctx.validation.valid and ctx.result.data and not is_overview:
        viz = reason_visualization(ctx.intent, ctx.result, ctx.schema_profile, is_primary=True)
        ctx.primary_viz = viz.dict()

    # Overview charts
    max_charts = settings.overview_charts + (1 if is_overview else 0)
    ctx.overview_charts = _build_overview_charts(
        ctx.schema_profile, ctx.df,
        exclude_title=ctx.primary_viz["title"] if ctx.primary_viz else "",
        max_charts=max_charts,
    )

    ctx.all_vizs = ([ctx.primary_viz] if ctx.primary_viz else []) + ctx.overview_charts


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
        intent_kpis=ctx.intent.requested_kpis,
        viz_specs=ctx.all_vizs,
        schema_profile=ctx.schema_profile,
    ).dict()


def step_build_layouts(ctx: PipelineContext) -> None:
    viz_spec_objs = [VizSpec(**v) for v in ctx.all_vizs[:4]]
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
            session_id=ctx.session_id,
            prompt=    ctx.prompt,
            intent=    ctx.intent,
            result=    ctx.result,
        )


def step_assemble(ctx: PipelineContext) -> dict:
    """Build the final API response dict from PipelineContext."""
    assert ctx.intent is not None

    return {
        "message":    f"Dashboard generated in {ctx.elapsed}s.",
        "session_id": ctx.session_id,
        "request_id": ctx.request_id,

        "analysis_report": {
            "query_intent":   ctx.intent.dict(),
            "plan_summary": {
                "formula_spec":     ctx.plan.formula_spec    if ctx.plan else "",
                "result_label":     ctx.plan.result_label    if ctx.plan else "",
                "metric_label":     ctx.plan.metric_label    if ctx.plan else "",
                "reasoning":        ctx.plan.reasoning       if ctx.plan else "",
                "confidence":       ctx.plan.confidence      if ctx.plan else 0.0,
                "operations_count": len(ctx.plan.operations) if ctx.plan else 0,
            },
            "validation":      ctx.validation.dict()    if ctx.validation else {},
            "insight_report":  ctx.insight_report,
            "confidence":      ctx.confidence.factors    if ctx.confidence else {},
            "confidence_tier": ctx.confidence.tier       if ctx.confidence else "unknown",
            "confidence_message": ctx.confidence.user_message if ctx.confidence else "",
        },

        "assumptions":   ctx.assumption_block.dict() if ctx.assumption_block else {},
        "kpi_coverage":  ctx.kpi_coverage or {},

        "visualizations": ctx.all_vizs,
        "layouts":        ctx.layouts,

        "executive_summary": ctx.dataset_output.get("executive_summary", []),
        "dataset_insights":  ctx.dataset_output.get("insights", []),

        "dataset_profile": _build_dataset_profile(ctx),

        "warnings": ctx.warnings,
    }


# ── Overview chart builder ────────────────────────────────────────
# (preserved from original, moved here to keep orchestrator self-contained)

def _build_overview_charts(
    schema_profile: dict,
    df:             pd.DataFrame,
    exclude_title:  str = "",
    max_charts:     int = 3,
) -> list[dict]:
    from app.core.models import QueryIntent, QuestionType, MetricType
    cols    = schema_profile.get("columns", [])
    dims    = [c for c in cols
               if c["role"] == "dimension"
               and c.get("semantic_hint") not in ("likely_id", "high_cardinality")
               and c["unique_count"] > 1]
    metrics = [c for c in cols if c["role"] == "metric"]
    dates   = [c for c in cols if c["role"] == "date"]

    candidates: list[dict] = []
    for d in dates[:1]:
        candidates.append({
            "question_type": QuestionType.trend, "metric": "count",
            "primary_dimension": d["name"], "time_column": d["name"], "sort_direction": "desc",
        })
    for dim in sorted(dims, key=lambda c: c["unique_count"])[:3]:
        candidates.append({
            "question_type": QuestionType.distribution, "metric": "count",
            "primary_dimension": dim["name"], "sort_direction": "desc", "top_n": 10,
        })
    for m in metrics[:2]:
        candidates.append({
            "question_type": QuestionType.distribution, "metric": "mean",
            "target_variable": m["name"],
            "primary_dimension": dims[0]["name"] if dims else None, "sort_direction": "desc",
        })

    charts: list[dict] = []
    for candidate in candidates:
        if len(charts) >= max_charts:
            break
        synthetic = QueryIntent(
            question_type=      candidate.get("question_type", QuestionType.distribution),
            metric=             candidate.get("metric", "count"),
            primary_dimension=  candidate.get("primary_dimension"),
            target_variable=    candidate.get("target_variable"),
            time_column=        candidate.get("time_column"),
            sort_direction=     candidate.get("sort_direction", "desc"),
            top_n=              candidate.get("top_n", 10),
            raw_prompt=         f"Overview of {candidate.get('primary_dimension', 'dataset')}",
        )
        plan   = build_analysis_plan(synthetic, schema_profile)
        result = execute_plan(plan, df)
        report = validate_result(synthetic, plan, result)
        if not report.valid or not result.data:
            continue
        viz = reason_visualization(synthetic, result, schema_profile, is_primary=False)
        if viz.title == exclude_title:
            continue
        charts.append(viz.dict())

    return charts


def _build_dataset_profile(ctx: PipelineContext) -> dict:
    if not ctx.schema_profile:
        return {}
    summary = ctx.schema_profile["dataset_summary"]
    return {
        "rows":         summary["rows"],
        "columns":      summary["columns"],
        "column_names": summary["column_names"],
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


# ── Main entry point ──────────────────────────────────────────────

def run_pipeline(
    file:       UploadFile,
    prompt:     str,
    session_id: str,
) -> dict:
    """
    Execute the full analysis pipeline and return a response dict.

    Raises:
        AmbiguityError  — if query is too ambiguous (caller handles)
        IngestionError  — if file cannot be loaded (caller maps to HTTP 400)
        Exception       — unexpected; caller maps to HTTP 500
    """
    ctx = PipelineContext(prompt=prompt, session_id=session_id)

    step_ingest(ctx, file)
    step_profile(ctx)
    step_session_load(ctx)
    step_query_understand(ctx)
    step_ambiguity_check(ctx)     # may raise AmbiguityError
    step_plan(ctx)
    step_execute_and_reflect(ctx)
    step_score_confidence(ctx)
    step_build_vizs(ctx)
    step_narrate(ctx)
    step_build_assumptions(ctx)
    step_compute_coverage(ctx)
    step_build_layouts(ctx)
    step_dataset_insights(ctx)
    step_session_save(ctx)

    response = step_assemble(ctx)
    logger.info("[%s] Pipeline complete in %.2fs — %d vizs, %d warnings",
                ctx.request_id, ctx.elapsed, len(ctx.all_vizs), len(ctx.warnings))
    return response
