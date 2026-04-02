from __future__ import annotations

from fastapi import APIRouter, Body

# intent_parser.py was deleted — replaced by query_understanding_agent
from app.layers.reasoning.query_understanding import understand_query
from app.services.schema_profiler import profile_dataframe

router = APIRouter(tags=["analyze"])


@router.post("/analyze")
async def analyze_prompt(payload: dict = Body(...)):
    prompt = payload.get("prompt", "")

    # New API accepts full schema_profile dict (richer than column list)
    # Also accepts legacy schema_columns list for backward compatibility
    schema_profile = payload.get("schema_profile", {})
    schema_columns = payload.get("schema_columns", [])

    # If caller passed old-style schema_columns list, build a minimal
    # schema_profile dict so understand_query() works correctly
    if not schema_profile and schema_columns:
        schema_profile = {
            "dataset_summary": {
                "rows": 0,
                "columns": len(schema_columns),
                "column_names": schema_columns,
            },
            "columns": [
                {
                    "name": col,
                    "dtype": "object",
                    "role": "dimension",
                    "semantic_hint": "none",
                    "unique_count": 0,
                    "null_percentage": 0.0,
                    "sample_values": [],
                    "top_values": [],
                }
                for col in schema_columns
            ],
        }

    intent = understand_query(prompt, schema_profile)

    return {
        "message": "Intent parsed successfully.",
        "intent": intent.dict(),
    }