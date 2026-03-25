from __future__ import annotations

from fastapi import APIRouter, Body

from app.services.coverage_engine import compute_kpi_coverage

router = APIRouter(tags=["coverage"])


@router.post("/coverage")
async def generate_coverage(payload: dict = Body(...)):
    intent = payload.get("intent", {})
    charts = payload.get("charts", [])

    coverage = compute_kpi_coverage(intent, charts)

    return {
        "message": "Coverage computed successfully.",
        "coverage": coverage,
    }