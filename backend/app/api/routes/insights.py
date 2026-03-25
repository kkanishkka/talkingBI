from __future__ import annotations

from fastapi import APIRouter, Body

from app.services.insight_engine import generate_insights

router = APIRouter(tags=["insights"])


@router.post("/generate-insights")
async def generate_insights_payload(payload: dict = Body(...)):
    intent = payload.get("intent", {})
    charts = payload.get("charts", [])
    schema_profile = payload.get("schema_profile", {})

    insight_output = generate_insights(intent, charts, schema_profile)

    return {
        "message": "Insights generated successfully.",
        "insight_summary": insight_output,
    }