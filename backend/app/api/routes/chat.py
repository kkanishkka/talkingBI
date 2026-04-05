"""
app/api/routes/chat.py
══════════════════════════════════════════════════════════════════════
POST /chat  —  Conversational BI endpoint

v3 changes vs session-1 version:
  ① schema_profile_cache accessed via proper Pydantic field (not
    a runtime __dict__ attribute) — thread-safe.
  ② Follow-up detection/resolution now delegates entirely to
    query_understanding._is_followup() and _resolve_followup() which
    are part of the core intent pipeline.  The old
    followup_resolver.build_resolved_prompt() string-manipulation
    approach is kept as a lightweight pre-pass for very short messages
    ("only electronics", "now top 10") before the full pipeline runs.
  ③ is_kpi_only flag surfaced in chat response.
  ④ _build_assistant_message() handles KPI results properly.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.exceptions import AmbiguityError, IngestionError
from app.core.session_store import session_store
from app.layers.ingestion.datasources.supabase import SupabaseDataSource
from app.pipeline.orchestrator import run_pipeline_from_dataframe
from app.schemas.connection import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — assistant message builder
# ═══════════════════════════════════════════════════════════════════

def _build_assistant_message(pipeline_response: dict, original_message: str) -> str:
    """
    Extract a short, plain-English assistant reply from the pipeline response.
    Priority order:
      1. Insight headline (narrative)
      2. KPI value (for scalar results)
      3. Plan result_label
      4. Generic fallback
    """
    report  = pipeline_response.get("analysis_report", {})
    insight = report.get("insight_report", {})
    headline = insight.get("headline", "")
    if headline:
        # Strip markdown bold for chat bubble display
        return headline.replace("**", "")

    # KPI result — format the value directly
    if pipeline_response.get("is_kpi_only"):
        vizs = pipeline_response.get("visualizations", [])
        if vizs:
            data = vizs[0].get("data", [])
            if data and "metric" in data[0]:
                return f"{data[0]['metric']}: {data[0].get('value', '—')}"

    plan  = report.get("plan_summary", {})
    label = plan.get("result_label", "")
    if label:
        return f"Here's your analysis: {label}."

    return f"Analysis complete for: \"{original_message}\""


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — follow-up suggestions from response
# ═══════════════════════════════════════════════════════════════════

def _get_suggestions(pipeline_response: dict) -> list[str]:
    return (
        pipeline_response.get("follow_up_suggestions")
        or pipeline_response.get("dashboard", {}).get("follow_up_suggestions")
        or []
    )


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — route
# ═══════════════════════════════════════════════════════════════════

@router.post("/chat")
def chat_query(payload: ChatRequest):
    """
    Conversational BI query endpoint.

    Accepts a natural-language message. If a session has previous
    turns, follow-up resolution is handled inside query_understanding
    (which has access to session context). The pipeline handles all
    intent resolution — this route's job is pure HTTP orchestration.
    """
    session_id = payload.session_id.strip()
    message    = payload.message.strip()

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty.")

    # ── 1. Validate session ───────────────────────────────────────
    connection_string = session_store.get_connection_string(session_id)
    selected_table    = session_store.get_selected_table(session_id)
    session_ctx       = session_store.get(session_id)

    if not connection_string or not session_ctx:
        raise HTTPException(
            status_code=404,
            detail="Session not found or database not connected. "
                   "Please reconnect and select a table first.",
        )
    if not selected_table:
        raise HTTPException(
            status_code=400,
            detail="No table selected. Please select a table before asking questions.",
        )

    # ── 2. Log follow-up context ──────────────────────────────────
    turn_count = len(session_ctx.conversation_turns)
    if turn_count > 0:
        logger.info(
            "[chat] Turn %d for session %s: '%s'",
            turn_count + 1, session_id[:8], message[:60],
        )

    # ── 3. Load dataframe ─────────────────────────────────────────
    try:
        ds = SupabaseDataSource(connection_string)
        df = ds.load_dataframe(selected_table, limit=50000)
    except Exception as exc:
        logger.exception("[chat] Failed to load table '%s'", selected_table)
        raise HTTPException(status_code=500, detail=f"Failed to load data: {exc}")

    # ── 4. Run pipeline ───────────────────────────────────────────
    # query_understanding() inside the pipeline already has access to
    # session_ctx (including previous_intent) and will resolve follow-ups.
    try:
        pipeline_response = run_pipeline_from_dataframe(
            df=          df,
            source_name= selected_table,
            prompt=      message,
            session_id=  session_id,
        )
    except AmbiguityError as exc:
        return JSONResponse(
            status_code=200,
            content={
                "type":                "clarification",
                "session_id":          session_id,
                "needs_clarification": True,
                "clarification":       exc.clarification,
                "message":             exc.user_message,
                "original_message":    message,
            },
        )
    except IngestionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message)
    except Exception as exc:
        logger.exception("[chat] Pipeline failed for: '%s'", message)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    # ── 5. Build response ─────────────────────────────────────────
    assistant_message = _build_assistant_message(pipeline_response, message)
    suggestions       = _get_suggestions(pipeline_response)

    # Refresh session context to get updated turn count
    refreshed = session_store.get(session_id)
    new_turn_count = len(refreshed.conversation_turns) if refreshed else turn_count + 1

    return {
        "type":              "answer",
        "session_id":        session_id,
        "original_message":  message,
        "assistant_message": assistant_message,

        # Full dashboard payload (same shape as /ask)
        "dashboard": pipeline_response,

        # Convenience top-level shortcuts for the chat UI
        "visualizations":    pipeline_response.get("visualizations", []),
        "is_kpi_only":       pipeline_response.get("is_kpi_only", False),
        "executive_summary": pipeline_response.get("executive_summary", []),
        "analysis_report":   pipeline_response.get("analysis_report", {}),
        "executed_query":    pipeline_response.get("executed_query", {}),
        "warnings":          pipeline_response.get("warnings", []),

        # Conversational extras
        "follow_up_suggestions": suggestions,
        "conversation_turn":     new_turn_count,
    }