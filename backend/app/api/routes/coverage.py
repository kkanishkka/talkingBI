from __future__ import annotations

from fastapi import APIRouter, Body

# coverage_engine.py was rewritten — compute_kpi_coverage now takes
# (intent_kpis: list[str], viz_specs: list[dict]) instead of (intent, charts)
from app.services.coverage_engine import compute_kpi_coverage

router = APIRouter(tags=["coverage"])


@router.post("/coverage")
async def generate_coverage(payload: dict = Body(...)):
    # Support both old-style and new-style callers:
    #   Old: {"intent": {...}, "charts": [...]}
    #   New: {"intent_kpis": [...], "viz_specs": [...]}

    intent_kpis = payload.get("intent_kpis", [])
    viz_specs   = payload.get("viz_specs",   [])

    # Legacy shim: extract requested_fields from old intent dict
    if not intent_kpis and "intent" in payload:
        old_intent  = payload["intent"]
        intent_kpis = old_intent.get("requested_kpis",
                      old_intent.get("requested_fields", []))

    # Legacy shim: use charts list as viz_specs
    if not viz_specs and "charts" in payload:
        viz_specs = payload["charts"]

    coverage = compute_kpi_coverage(intent_kpis, viz_specs)

    return {
        "message":  "Coverage computed successfully.",
        "coverage": coverage.dict(),
    }