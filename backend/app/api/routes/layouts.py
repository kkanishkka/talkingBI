from __future__ import annotations

from fastapi import APIRouter, Body

# layout_generator.py was deleted — replaced by build_dashboard_layouts()
# inside viz_reasoning_agent.py
from app.services.viz_reasoning_agent import build_dashboard_layouts
from app.core.models import VizSpec

router = APIRouter(tags=["layouts"])


@router.post("/generate-layouts")
async def generate_layout_payload(payload: dict = Body(...)):
    charts = payload.get("charts", [])

    # Convert incoming chart dicts to VizSpec objects
    # Accept both old-style chart dicts and new VizSpec dicts
    viz_specs = []
    for c in charts[:4]:
        try:
            # New-style: has chart_type, x_field, y_field, data
            viz_specs.append(VizSpec(
                chart_type=     c.get("chart_type", "bar"),
                title=          c.get("title", "Chart"),
                x_field=        c.get("x_field", c.get("fields", [""])[0] if c.get("fields") else ""),
                y_field=        c.get("y_field", "value"),
                data=           c.get("data", []),
                why_this_chart= c.get("why_this_chart", ""),
                confidence=     float(c.get("confidence", 0.80)),
            ))
        except Exception:
            # Skip malformed entries rather than crashing
            continue

    layout_objs = build_dashboard_layouts(viz_specs)
    layouts     = [lo.dict() for lo in layout_objs]

    return {
        "message": "Dashboard layouts generated successfully.",
        "layouts": layouts,
    }