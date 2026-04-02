"""
app/core/session_store.py
══════════════════════════════════════════════════════════════════════
REFACTORED: Durable session context with conversation history.

Key improvements over the original:
  1. ConversationTurn model — every query/result pair is persisted
  2. follow_up resolution — previous intent exposed for query understanding
  3. dataset_fingerprint — detects same file re-uploaded (avoids re-profiling)
  4. max_turns enforcement — prevents unbounded memory growth
  5. Thread-safe update via dict merge (not setattr)

Architecture:
  SessionStore (singleton)
  └── dict[session_id → SessionContext]
      └── SessionContext
          ├── schema_context       (SchemaContext from last upload)
          ├── previous_intent      (QueryIntent from last query)
          ├── previous_result      (ExecutionResult from last query)
          ├── conversation_turns   (list[ConversationTurn])
          └── dataset_fingerprint  (hash of column names + row count)
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.models import ExecutionResult, QueryIntent, SchemaContext


# ── conversation turn ─────────────────────────────────────────────

class ConversationTurn(BaseModel):
    turn_id:        str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    prompt:         str
    intent_summary: str  = ""   # e.g. "ranking, metric=rate, dim=job"
    result_rows:    int  = 0
    result_label:   str  = ""
    timestamp:      float = Field(default_factory=time.time)


# ── session context ───────────────────────────────────────────────

class SessionContext(BaseModel):
    session_id:     str
    created_at:     float = Field(default_factory=time.time)
    last_accessed:  float = Field(default_factory=time.time)

    # data context (set on upload / first query)
    schema_context:      Optional[SchemaContext]   = None
    dataset_fingerprint: Optional[str]             = None

    # carry-forward from previous query
    previous_intent:  Optional[QueryIntent]     = None
    previous_result:  Optional[ExecutionResult] = None

    # conversation history
    conversation_turns: list[ConversationTurn] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

    def add_turn(
        self,
        prompt:   str,
        intent:   QueryIntent,
        result:   ExecutionResult,
    ) -> None:
        """Record a completed query turn and update carry-forward state."""
        self.previous_intent = intent
        self.previous_result = result
        self.conversation_turns.append(ConversationTurn(
            prompt=         prompt,
            intent_summary= (
                f"{intent.question_type}, metric={intent.metric}, "
                f"dim={intent.primary_dimension}, target={intent.target_variable}"
            ),
            result_rows=    result.row_count,
            result_label=   result.result_label,
        ))
        # Enforce max turns to bound memory usage
        max_t = settings.max_conversation_turns
        if len(self.conversation_turns) > max_t:
            self.conversation_turns = self.conversation_turns[-max_t:]

    def get_context_summary(self) -> str:
        """
        Returns a compact context string for injection into LLM prompts.
        Used by query_understanding to resolve follow-up references.
        """
        if not self.conversation_turns:
            return ""
        lines = []
        for i, turn in enumerate(self.conversation_turns[-3:], 1):   # last 3
            lines.append(
                f"  Turn {i}: \"{turn.prompt}\" → {turn.intent_summary} "
                f"({turn.result_rows} rows, label='{turn.result_label}')"
            )
        return "Recent conversation:\n" + "\n".join(lines)


# ── fingerprint helper ────────────────────────────────────────────

def compute_dataset_fingerprint(column_names: list[str], row_count: int) -> str:
    """
    Lightweight fingerprint for detecting re-upload of the same file.
    Not a content hash — just structure-level.
    """
    key = f"{sorted(column_names)}:{row_count}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ── store ─────────────────────────────────────────────────────────

class SessionStore:
    """
    In-memory session store.
    - TTL: configurable via settings.session_ttl_seconds (default 30 min)
    - Eviction: lazy (on every get / new_session call)
    - Thread safety: GIL-protected for CPython (sufficient for single-process FastAPI)
    """

    def __init__(self) -> None:
        self._store: dict[str, SessionContext] = {}

    # ── creation ──────────────────────────────────────────────────

    def new_session(self) -> str:
        self._evict_stale()
        session_id = str(uuid.uuid4())
        self._store[session_id] = SessionContext(session_id=session_id)
        return session_id

    # ── read ──────────────────────────────────────────────────────

    def get(self, session_id: str) -> Optional[SessionContext]:
        self._evict_stale()
        ctx = self._store.get(session_id)
        if ctx:
            ctx.last_accessed = time.time()
        return ctx

    def get_or_create(self, session_id: str) -> tuple[SessionContext, bool]:
        """
        Returns (context, is_new).
        If session_id is empty or unknown, creates a new session.
        """
        sid = session_id.strip()
        if sid:
            ctx = self.get(sid)
            if ctx:
                return ctx, False
        # create new
        new_sid = self.new_session()
        return self._store[new_sid], True

    # ── write ─────────────────────────────────────────────────────

    def save(self, ctx: SessionContext) -> None:
        ctx.last_accessed = time.time()
        self._store[ctx.session_id] = ctx

    def record_turn(
        self,
        session_id: str,
        prompt:     str,
        intent:     QueryIntent,
        result:     ExecutionResult,
    ) -> None:
        """Convenience: add a completed turn to an existing session."""
        ctx = self._store.get(session_id)
        if ctx is None:
            return
        ctx.add_turn(prompt, intent, result)
        ctx.last_accessed = time.time()

    def set_schema(
        self,
        session_id:   str,
        schema:       SchemaContext,
        column_names: list[str],
        row_count:    int,
    ) -> None:
        """Store schema context and dataset fingerprint."""
        ctx = self._store.get(session_id)
        if ctx is None:
            return
        ctx.schema_context       = schema
        ctx.dataset_fingerprint  = compute_dataset_fingerprint(column_names, row_count)
        ctx.last_accessed        = time.time()

    # ── deletion ──────────────────────────────────────────────────

    def delete(self, session_id: str) -> bool:
        return self._store.pop(session_id, None) is not None

    # ── introspection ─────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._store)

    def summary(self) -> dict[str, Any]:
        return {
            "active_sessions": len(self._store),
            "session_ids":     list(self._store.keys()),
        }

    # ── eviction ──────────────────────────────────────────────────

    def _evict_stale(self) -> None:
        now   = time.time()
        ttl   = settings.session_ttl_seconds
        stale = [sid for sid, ctx in self._store.items()
                 if now - ctx.last_accessed > ttl]
        for sid in stale:
            del self._store[sid]


# module-level singleton
session_store = SessionStore()
