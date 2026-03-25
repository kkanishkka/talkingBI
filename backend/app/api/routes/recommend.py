from __future__ import annotations

from fastapi import APIRouter, Body

from app.services.chart_recommender import recommend_charts

router = APIRouter(tags=["recommend"])


@router.post("/recommend-charts")
async def recommend_chart_payload(payload: dict = Body(...)):
    intent = payload.get("intent", {})
    schema_profile = payload.get("schema_profile", {})

    charts = recommend_charts(intent, schema_profile)

    return {
        "message": "Chart recommendations generated successfully.",
        "charts": charts,
    }