"""
app/api/routes/upload.py
══════════════════════════════════════════════════════════════════════
REFACTORED: Session-aware file upload endpoint.

Changes from original:
  - Uses ingestion layer (loader.py) instead of inline pd.read_csv
  - Creates / resumes a session on upload
  - Stores schema_context in session for follow-up queries
  - Returns session_id so frontend can pass it to /dashboard
  - Validation warnings included in response
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.exceptions import IngestionError
from app.core.session_store import session_store
from app.layers.ingestion.loader import load_dataframe, validate_dataframe
from app.layers.semantic.schema_profiler import build_schema_context, profile_dataframe

logger = logging.getLogger(__name__)
router = APIRouter(tags=["upload"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    try:
        df, filename = load_dataframe(file)
        warnings     = validate_dataframe(df, filename)
        profile      = profile_dataframe(df)
        schema_ctx   = build_schema_context(profile)

        # Create session and store schema
        session_id  = session_store.new_session()
        col_names   = profile["dataset_summary"]["column_names"]
        row_count   = profile["dataset_summary"]["rows"]
        session_store.set_schema(session_id, schema_ctx, col_names, row_count)

        logger.info("Upload: '%s' → session %s (%d rows)", filename, session_id[:8], row_count)

        return {
            "filename":    filename,
            "session_id":  session_id,
            "message":     "File uploaded and profiled successfully.",
            "profile":     profile,
            "preview_rows": df.head(5).fillna("").to_dict(orient="records"),
            "warnings":    warnings,
        }

    except IngestionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Upload failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to process file: {exc}")
