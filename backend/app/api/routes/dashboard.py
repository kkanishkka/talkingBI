"""
app/api/routes/dashboard.py
══════════════════════════════════════════════════════════════════════
Single entry point. Clean 6-agent pipeline. No dual paths.

Pipeline:
  1  Load DataFrame
  2  Profile schema + semantic enrichment   (schema_profiler)
  3  Query Understanding                    (query_understanding_agent)
  4  Analysis Planning                      (analysis_planning_agent)
  5  Execution                              (analysis_executor)
  6  Reflection + optional refinement       (reflection_agent + plan_refinement)
  7  Viz Reasoning                          (viz_reasoning_agent)
  8  Insight Narration                      (insight_narration_agent)
  9  Assumption block                       (insight_narration_agent)
  10 KPI Coverage                           (coverage_engine)
  11 Dashboard Layouts                      (viz_reasoning_agent)
  12 Dataset insights                       (insight_engine)
  13 Assemble + return DashboardResponse

Overview charts are generated using the same pipeline with
synthetic intents — no separate code path.

Response shape (see app/core/models.py DashboardResponse):
  analysis_report, assumptions, kpi_coverage,
  visualizations, layouts,
  executive_summary, dataset_insights, dataset_profile,
  session_id, warnings
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import io
import logging
import time
import uuid
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.models import (
    AnalysisPlan, AssumptionBlock, DashboardResponse, ExecutionResult,
    KPICoverage, QueryIntent, QuestionType, VizSpec,
)
from app.core.session_store import session_store
from app.services.schema_profiler import profile_dataframe, build_schema_context
from app.services.query_understanding_agent import understand_query
from app.services.analysis_planning_agent import build_analysis_plan
from app.services.analysis_executor import execute_plan
from app.services.reflection_agent import validate_result
from app.services.plan_refinement import refine_and_execute
from app.services.viz_reasoning_agent import reason_visualization, build_dashboard_layouts
from app.services.insight_narration_agent import narrate_insights, build_assumption_block
from app.services.insight_engine import generate_dataset_insights
from app.services.coverage_engine import compute_kpi_coverage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])


# ── file loader ───────────────────────────────────────────────────

def _load_dataframe(file: UploadFile) -> pd.DataFrame:
    filename = file.filename or ""
    ext      = filename.lower().rsplit(".", 1)[-1]
    raw      = file.file.read()
    if ext == "csv":
        return pd.read_csv(io.BytesIO(raw))
    if ext in {"xlsx", "xls"}:
        return pd.read_excel(io.BytesIO(raw))
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type '{ext}'. Please upload CSV or Excel.",
    )


# ── overview chart generator ──────────────────────────────────────

def _build_overview_charts(
    schema_profile: dict[str, Any],
    df:             pd.DataFrame,
    exclude_title:  str = "",
    max_charts:     int = 3,
) -> list[dict[str, Any]]:
    """
    Build supporting overview charts using the same pipeline.
    Uses synthetic intents per interesting column.
    """
    cols      = schema_profile.get("columns", [])
    dims      = [c for c in cols
                 if c["role"] == "dimension"
                 and c.get("semantic_hint") not in ("likely_id", "high_cardinality")
                 and c["unique_count"] > 1]
    metrics   = [c for c in cols if c["role"] == "metric"]
    dates     = [c for c in cols if c["role"] == "date"]

    candidates: list[dict[str, Any]] = []

    # date trends first
    for d in dates[:1]:
        candidates.append({
            "question_type": QuestionType.trend,
            "metric":        "count",
            "primary_dimension": d["name"],
            "time_column":   d["name"],
            "sort_direction": "desc",
        })

    # low-cardinality dims
    for dim in sorted(dims, key=lambda c: c["unique_count"])[:3]:
        candidates.append({
            "question_type": QuestionType.distribution,
            "metric":        "count",
            "primary_dimension": dim["name"],
            "sort_direction": "desc",
            "top_n":         10,
        })

    # metrics
    for m in metrics[:2]:
        candidates.append({
            "question_type": QuestionType.distribution,
            "metric":        "mean",
            "target_variable": m["name"],
            "primary_dimension": (dims[0]["name"] if dims else None),
            "sort_direction": "desc",
        })

    charts: list[dict[str, Any]] = []
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


# ── main endpoint ─────────────────────────────────────────────────

@router.post("/dashboard", response_model=None)
async def generate_dashboard(
    file:       UploadFile = File(...),
    prompt:     str        = Form(default="Give me a complete overview dashboard"),
    session_id: str        = Form(default=""),
):
    t0 = time.time()
    warnings_out: list[str] = []

    # ── 1. Load data ──────────────────────────────────────────────
    try:
        df = _load_dataframe(file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"File parsing failed: {exc}") from exc

    # ── 2. Profile ────────────────────────────────────────────────
    schema_profile = profile_dataframe(df)
    schema_context = build_schema_context(schema_profile)

    # ── 3. Session ────────────────────────────────────────────────
    sid = session_id.strip() or str(uuid.uuid4())
    session_store.update(
        sid,
        schema_context=schema_context,
        last_accessed=time.time(),
    )

    # ── 4. Query understanding ────────────────────────────────────
    intent = understand_query(prompt, schema_profile)
    logger.info(
        "Dashboard [%s]: type=%s metric=%s dim=%s target=%s",
        sid[:8], intent.question_type, intent.metric,
        intent.primary_dimension, intent.target_variable,
    )

    # ── 5. Planning ───────────────────────────────────────────────
    plan = build_analysis_plan(intent, schema_profile)

    # ── 6. Execution + reflection + optional refinement ───────────
    result   = execute_plan(plan, df)
    report   = validate_result(intent, plan, result)
    ref_log: list[str] = []

    if not report.valid and report.is_retryable:
        result, report, ref_log = refine_and_execute(
            intent, plan, result, report, schema_profile, df
        )
        if ref_log:
            warnings_out.extend(ref_log)

    if result.sample_warning:
        warnings_out.append(result.sample_warning)

    # ── 7. Viz reasoning ──────────────────────────────────────────
    primary_viz: dict[str, Any] | None = None
    is_overview = (str(intent.question_type) == QuestionType.overview)

    if report.valid and result.data and not is_overview:
        viz = reason_visualization(intent, result, schema_profile, is_primary=True)
        primary_viz = viz.dict()

    # ── 8. Overview charts ────────────────────────────────────────
    overview_charts = _build_overview_charts(
        schema_profile,
        df,
        exclude_title=primary_viz["title"] if primary_viz else "",
        max_charts=3 if not is_overview else 4,
    )

    all_vizs: list[dict[str, Any]] = []
    if primary_viz:
        all_vizs.append(primary_viz)
    all_vizs.extend(overview_charts)

    # ── 9. Insight narration ──────────────────────────────────────
    insight_report = {}
    if report.valid and result.data and not is_overview:
        ir = narrate_insights(intent, result, primary_viz)
        insight_report = ir.dict()

    # ── 10. Assumption block ──────────────────────────────────────
    assumption_block = build_assumption_block(
        intent, plan.formula_spec
    ).dict()

    # ── 11. KPI coverage ──────────────────────────────────────────
    kpi_coverage = compute_kpi_coverage(
        intent_kpis= intent.requested_kpis,
        viz_specs=   all_vizs,
    ).dict()

    # ── 12. Dashboard layouts ─────────────────────────────────────
    viz_spec_objs = [VizSpec(**v) for v in all_vizs[:4]]
    layouts = [l.dict() for l in build_dashboard_layouts(viz_spec_objs)]

    # ── 13. Dataset insights ──────────────────────────────────────
    dataset_output = generate_dataset_insights(
        schema_profile,
        {"raw_prompt": prompt, "business_goal": prompt},
    )

    # ── 14. Validation warnings ───────────────────────────────────
    if not report.valid:
        warnings_out.extend(report.issues)
    warnings_out.extend(report.warnings)

    elapsed = round(time.time() - t0, 2)
    logger.info("Dashboard [%s]: generated in %.2fs, vizs=%d", sid[:8], elapsed, len(all_vizs))

    # ── 15. Assemble response ─────────────────────────────────────
    return {
        "message": f"Dashboard generated in {elapsed}s.",
        "session_id": sid,

        # primary query output
        "analysis_report": {
            "query_intent":   intent.dict(),
            "plan_summary":   {
                "formula_spec":  plan.formula_spec,
                "result_label":  plan.result_label,
                "metric_label":  plan.metric_label,
                "reasoning":     plan.reasoning,
                "confidence":    plan.confidence,
                "operations_count": len(plan.operations),
            },
            "validation":     report.dict(),
            "insight_report": insight_report,
        },

        "assumptions":    assumption_block,
        "kpi_coverage":   kpi_coverage,

        # charts and layouts
        "visualizations": all_vizs,
        "layouts":        layouts,

        # dataset-level context
        "executive_summary": dataset_output["executive_summary"],
        "dataset_insights":  dataset_output["insights"],

        "dataset_profile": {
            "rows":    schema_profile["dataset_summary"]["rows"],
            "columns": schema_profile["dataset_summary"]["columns"],
            "column_names": schema_profile["dataset_summary"]["column_names"],
            "column_details": [
                {
                    "name":            c["name"],
                    "dtype":           c["dtype"],
                    "role":            c["role"],
                    "semantic_hint":   c.get("semantic_hint", "none"),
                    "unique_count":    c["unique_count"],
                    "null_percentage": c["null_percentage"],
                }
                for c in schema_profile["columns"]
            ],
        },

        "warnings": warnings_out,
    }