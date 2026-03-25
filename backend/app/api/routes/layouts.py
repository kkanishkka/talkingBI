from __future__ import annotations

from fastapi import APIRouter, Body

from app.services.layout_generator import generate_layouts

router = APIRouter(tags=["layouts"])


@router.post("/generate-layouts")
async def generate_layout_payload(payload: dict = Body(...)):
    charts = payload.get("charts", [])

    layouts = generate_layouts(charts)

    return {
        "message": "Dashboard layouts generated successfully.",
        "layouts": layouts,
    }