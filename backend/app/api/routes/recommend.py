from __future__ import annotations

from fastapi import APIRouter, Body

# chart_recommender.py was deleted — replaced by viz_reasoning_agent
# For the standalone /recommend-charts endpoint we need a compatible shim.
# We build a synthetic ExecutionResult from the schema and return VizSpecs.
from app.services.viz_reasoning_agent import reason_visualization, build_dashboard_layouts
from app.services.query_understanding_agent import understand_query
from app.services.analysis_planning_agent import build_analysis_plan

router = APIRouter(tags=["recommend"])


@router.post("/recommend-charts")
async def recommend_chart_payload(payload: dict = Body(...)):
    intent_dict    = payload.get("intent", {})
    schema_profile = payload.get("schema_profile", {})

    # Re-derive intent from the raw_prompt if present, else build from dict
    raw_prompt = intent_dict.get("raw_prompt", "Give me an overview")
    intent     = understand_query(raw_prompt, schema_profile)

    # Build a plan so we know x_field / y_field / metric_label
    plan = build_analysis_plan(intent, schema_profile)

    # Return a lightweight chart spec without running actual execution
    # (this endpoint is used for preview/exploration only)
    cols    = schema_profile.get("columns", [])
    dims    = [c for c in cols if c.get("role") == "dimension"
               and c.get("semantic_hint") not in ("likely_id", "high_cardinality")
               and c.get("unique_count", 0) > 1]
    metrics = [c for c in cols if c.get("role") == "metric"]
    dates   = [c for c in cols if c.get("role") == "date"]

    # Produce lightweight chart spec stubs (no real data)
    charts = []
    for col in (dates[:1] + dims[:3] + metrics[:2]):
        role = col.get("role", "dimension")
        ctype = "line" if role == "date" else (
            "bar" if role == "dimension" else "kpi_card"
        )
        charts.append({
            "chart_type":    ctype,
            "title":         f"{col['name']} overview",
            "fields":        [col["name"]],
            "why_this_chart": f"Selected based on column role: {role}",
            "confidence":    0.80,
        })

    return {
        "message": "Chart recommendations generated successfully.",
        "charts":  charts[:6],
    }