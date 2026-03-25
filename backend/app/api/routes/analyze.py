from __future__ import annotations

from fastapi import APIRouter, Body

from app.services.intent_parser import parse_intent

router = APIRouter(tags=["analyze"])


@router.post("/analyze")
async def analyze_prompt(payload: dict = Body(...)):
    prompt = payload.get("prompt", "")
    schema_columns = payload.get("schema_columns", [])

    result = parse_intent(prompt, schema_columns)

    return {
        "message": "Intent parsed successfully.",
        "intent": result,
    }