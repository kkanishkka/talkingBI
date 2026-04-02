"""
app/api/routes/session.py
══════════════════════════════════════════════════════════════════════
NEW: Session management endpoints.

  GET  /session/{session_id}         — retrieve session info + history
  DELETE /session/{session_id}       — end session (clear context)
  GET  /session/{session_id}/history — conversation turn history

These allow the frontend to:
  - Show "continuing from your last analysis" context
  - Build a conversation history panel
  - Let users explicitly reset a session
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.session_store import session_store

router = APIRouter(prefix="/session", tags=["session"])


@router.get("/{session_id}")
def get_session(session_id: str):
    ctx = session_store.get(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found or expired.")

    return {
        "session_id":    ctx.session_id,
        "created_at":    ctx.created_at,
        "last_accessed": ctx.last_accessed,
        "turn_count":    len(ctx.conversation_turns),
        "has_schema":    ctx.schema_context is not None,
        "fingerprint":   ctx.dataset_fingerprint,
        "previous_query": (
            ctx.conversation_turns[-1].prompt
            if ctx.conversation_turns else None
        ),
    }


@router.get("/{session_id}/history")
def get_session_history(session_id: str):
    ctx = session_store.get(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found or expired.")

    return {
        "session_id": ctx.session_id,
        "turns": [
            {
                "turn_id":        turn.turn_id,
                "prompt":         turn.prompt,
                "intent_summary": turn.intent_summary,
                "result_rows":    turn.result_rows,
                "result_label":   turn.result_label,
                "timestamp":      turn.timestamp,
            }
            for turn in ctx.conversation_turns
        ],
    }


@router.delete("/{session_id}")
def delete_session(session_id: str):
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"message": f"Session '{session_id}' deleted.", "deleted": True}
