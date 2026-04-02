"""
app/api/routes/dashboard.py
══════════════════════════════════════════════════════════════════════
REFACTORED: Thin API layer — all logic lives in pipeline/orchestrator.py

This file's only jobs:
  1. Parse HTTP inputs (file, prompt, session_id)
  2. Call run_pipeline()
  3. Map typed exceptions → HTTP responses
  4. Return response

No business logic here.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.core.exceptions import AmbiguityError, IngestionError, TalkingBIError
from app.pipeline.orchestrator import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])


@router.post("/dashboard", response_model=None)
async def generate_dashboard(
    file:       UploadFile = File(...),
    prompt:     str        = Form(default="Give me a complete overview dashboard"),
    session_id: str        = Form(default=""),
):
    try:
        return run_pipeline(file=file, prompt=prompt, session_id=session_id)

    except AmbiguityError as exc:
        # Not a failure — frontend should render clarification UI
        return JSONResponse(
            status_code=200,
            content={
                "needs_clarification": True,
                "clarification":       exc.clarification,
                "session_id":          session_id,
                "message":             exc.user_message,
            },
        )

    except IngestionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message)

    except TalkingBIError as exc:
        logger.error("Pipeline error [%s]: %s", exc.layer, exc)
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message)

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Unexpected pipeline error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again.",
        )
