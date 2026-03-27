"""
app/api/routes/dashboard.py
────────────────────────────────────────────────────────────────────
Single combined endpoint that:
  1. Receives an uploaded file + optional natural-language prompt
  2. Profiles the schema  (schema_profiler)
  3. Parses intent        (intent_parser)
  4. Recommends charts    (chart_recommender)
  5. Generates insights   (insight_engine)
  6. Materialises chart-ready data from the actual DataFrame
  7. Returns one clean JSON response the frontend can render generically

No existing service is rewritten — this router is the only new file.
────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

#from curses import raw
import io
from typing import Any
import logging

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.schema_profiler import profile_dataframe
#from app.services.intent_parser import parse_intent
#from app.services.chart_recommender import recommend_charts
from app.services.insight_engine import generate_insights


from app.services.query_understanding_agent import understand_query
from app.services.analysis_planning_agent import build_analysis_plan
from app.services.analysis_executor import execute_plan
from app.services.reflection_agent import validate_result
from app.services.viz_reasoning_agent import reason_visualization
from app.services.insight_narration_agent import narrate_insights

router = APIRouter(tags=["dashboard"])
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


def _load_dataframe(file: UploadFile) -> pd.DataFrame:
    filename = file.filename or ""
    ext      = filename.lower().rsplit(".", 1)[-1]
    raw      = file.file.read()
    if ext == "csv":
        return pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
    if ext in {"xlsx", "xls"}:
        return pd.read_excel(io.BytesIO(raw))
    raise HTTPException(
        status_code=400,
        detail="Unsupported file type. Please upload a CSV or Excel file.",
    )
 
 
# ── legacy materialise (fallback overview charts) ─────────────────
 
def _materialise_overview_charts(
    schema_profile: dict[str, Any],
    df: pd.DataFrame,
    num_charts: int = 4,
) -> list[dict[str, Any]]:
    """
    Generate generic overview charts for the full dataset (no query).
    This is the legacy path used when the query is empty / generic.
    """
    from app.services.viz_reasoning_agent import reason_visualization
    from app.services.query_understanding_agent import understand_query
    from app.services.analysis_planning_agent import build_analysis_plan
    from app.services.analysis_executor import execute_plan
 
    cols     = schema_profile.get("columns", [])
    dims     = [c for c in cols if c["role"] == "dimension" and c["unique_count"] > 1]
    metrics  = [c for c in cols if c["role"] == "metric"]
    dates    = [c for c in cols if c["role"] == "date"]
 
    visualizations: list[dict[str, Any]] = []
 
    # chart candidates: date trends + dimensions + metrics
    candidates = (
        [(d, "trend",        "count") for d in dates[:1]]
        + [(d, "ranking",    "count") for d in sorted(dims, key=lambda c: c["unique_count"])[:3]]
        + [(m, "aggregation","mean")  for m in metrics[:2]]
    )
 
    for col_profile, qtype, metric in candidates:
        if len(visualizations) >= num_charts:
            break
 
        col_name = col_profile["name"]
 
        # build a minimal synthetic intent for this column
        synthetic_intent = {
            "question_type":     qtype,
            "primary_dimension": col_name if col_profile["role"] != "metric" else None,
            "target_variable":   col_name if col_profile["role"] == "metric" else None,
            "metric":            metric,
            "filter":            None,
            "time_column":       col_name if col_profile["role"] == "date" else None,
            "sort_direction":    "desc",
            "top_n":             10,
            "raw_prompt":        f"Overview of {col_name}",
            "num_visualizations": 1,
        }
 
        plan   = build_analysis_plan(synthetic_intent, schema_profile)
        result = execute_plan(plan, df)
 
        if not result["success"] or not result["data"]:
            continue
 
        viz = reason_visualization(synthetic_intent, result, schema_profile)
        viz["why_this_chart"] = f"Overview: {col_profile.get('role', 'column')} analysis of {col_name}."
        visualizations.append(viz)
 
    return visualizations
 
 
# ── main endpoint ─────────────────────────────────────────────────
 
@router.post("/dashboard")
async def generate_dashboard(
    file:   UploadFile = File(...),
    prompt: str        = Form(default="Give me a complete overview dashboard"),
):
    """
    TalkingBI main endpoint.
    Routes through the 6-agent pipeline for query-specific analysis,
    with legacy overview charts as a complement/fallback.
    """
    # 1 — load data
    try:
        df = _load_dataframe(file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"File parsing failed: {exc}") from exc
 
    # 2 — profile schema
    schema_profile = profile_dataframe(df)
 
    # ── AGENT PIPELINE ──────────────────────────────────────────
 
    # 3 — query understanding
    query_intent = understand_query(prompt, schema_profile)
    logger.info(
        "Query understood: type=%s, metric=%s, dim=%s, target=%s, source=%s",
        query_intent.get("question_type"),
        query_intent.get("metric"),
        query_intent.get("primary_dimension"),
        query_intent.get("target_variable"),
        query_intent.get("_source"),
    )
 
    # 4 — analysis planning
    analysis_plan = build_analysis_plan(query_intent, schema_profile)
    logger.info(
        "Analysis planned: %d operations, source=%s",
        len(analysis_plan.get("operations", [])),
        analysis_plan.get("_source"),
    )
 
    # 5 — execution (deterministic pandas)
    execution_result = execute_plan(analysis_plan, df)
    logger.info(
        "Execution: success=%s, rows=%d",
        execution_result["success"],
        execution_result["row_count"],
    )
 
    # 6 — reflection / validation
    validation = validate_result(query_intent, analysis_plan, execution_result)
    logger.info(
        "Validation: valid=%s, quality=%.2f, issues=%s",
        validation["valid"],
        validation["quality_score"],
        validation["issues"],
    )
 
    # 7 — visualization reasoning
    primary_viz: dict[str, Any] | None = None
    if validation["valid"] and execution_result.get("data"):
        primary_viz = reason_visualization(query_intent, execution_result, schema_profile)
 
    # 8 — insight narration
    insight_report: dict[str, Any] = {}
    if validation["valid"] and execution_result.get("data"):
        insight_report = narrate_insights(query_intent, execution_result, primary_viz or {})
 
    # ── FALLBACK / OVERVIEW CHARTS ──────────────────────────────
    # Always generate overview charts for dataset-level exploration.
    # If primary_viz exists, prepend it (most relevant first).
    overview_vizs = _materialise_overview_charts(schema_profile, df, num_charts=4)
 
    visualizations: list[dict[str, Any]] = []
    if primary_viz:
        primary_viz["is_primary"] = True
        primary_viz["confidence"] = analysis_plan.get("confidence", 0.85)
        visualizations.append(primary_viz)
    visualizations.extend(overview_vizs)
 
    # ── OVERVIEW INSIGHTS (legacy, for the insights panel) ─────
    # These cover dataset-level patterns (cross-column, quality, schema mix).
    # The query-specific insight is in analysis_report.insight_report.
    overview_insights_output = generate_insights(
        intent={
            "requested_fields": schema_profile["dataset_summary"]["column_names"],
            "analysis_tasks":   [query_intent.get("question_type", "distribution")],
            "business_goal":    query_intent.get("raw_prompt", ""),
        },
        charts=[],
        schema_profile=schema_profile,
    )
 
    # ── BUILD RESPONSE ──────────────────────────────────────────
    return {
        "message": "Dashboard generated successfully.",
 
        # dataset profile (unchanged shape for frontend)
        "dataset_profile": {
            "rows":    schema_profile["dataset_summary"]["rows"],
            "columns": schema_profile["dataset_summary"]["columns"],
            "column_names": schema_profile["dataset_summary"]["column_names"],
            "column_details": [
                {
                    "name":            c["name"],
                    "dtype":           c["dtype"],
                    "role":            c["role"],
                    "unique_count":    c["unique_count"],
                    "null_percentage": c["null_percentage"],
                }
                for c in schema_profile["columns"]
            ],
        },
 
        # overview: executive summary bullets + dataset insights
        "executive_summary": overview_insights_output.get("executive_summary", []),
        "insights":          overview_insights_output.get("insights", []),
 
        # charts (primary query chart first, then overview)
        "visualizations": visualizations,
 
        # NEW: structured analysis output for query-specific display
        "analysis_report": {
            "query_intent":   query_intent,
            "analysis_plan":  {
                "operations":   analysis_plan.get("operations", []),
                "result_label": analysis_plan.get("result_label", ""),
                "metric_label": analysis_plan.get("metric_label", ""),
                "reasoning":    analysis_plan.get("reasoning", ""),
                "confidence":   analysis_plan.get("confidence", 0),
            },
            "validation":     validation,
            "insight_report": insight_report,
        },
    }