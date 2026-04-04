from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.exceptions import AmbiguityError, IngestionError
from app.core.session_store import session_store
from app.layers.ingestion.datasources.supabase import SupabaseDataSource
from app.pipeline.orchestrator import run_pipeline_from_dataframe
from app.schemas.connection import AskRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ask"])


@router.post("/ask")
def ask_question(payload: AskRequest):
    connection_string = session_store.get_connection_string(payload.session_id)
    selected_table    = session_store.get_selected_table(payload.session_id)

    if not connection_string:
        raise HTTPException(
            status_code=404,
            detail="Session not found or database not connected.",
        )
    if not selected_table:
        raise HTTPException(
            status_code=400,
            detail="No table selected for this session.",
        )

    try:
        ds = SupabaseDataSource(connection_string)
        df = ds.load_dataframe(selected_table, limit=50000)

        return run_pipeline_from_dataframe(
            df=df,
            source_name=selected_table,
            prompt=payload.prompt,
            session_id=payload.session_id,
        )

    except AmbiguityError as exc:
        return JSONResponse(
            status_code=200,
            content={
                "needs_clarification": True,
                "clarification":       exc.clarification,
                "session_id":          payload.session_id,
                "message":             exc.user_message,
            },
        )
    except IngestionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message)
    except Exception as exc:
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}")