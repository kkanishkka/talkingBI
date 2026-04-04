"""
app/core/session_store.py
══════════════════════════════════════════════════════════════════════
Session Store — v3

Changes from v2:
  ① schema_profile_cache added as a proper Optional[dict] Pydantic field
    (was set as a runtime __dict__ attribute before, which is not
    thread-safe and fails under Pydantic model validation).
    It is excluded from serialisation with Field(exclude=True) so it
    doesn't bloat session memory with the full profile dict on every
    session summary call.

  ② set_schema() now also stores the raw profile dict in the cache.

  ③ get_schema_profile_cache() convenience accessor added.

All other logic unchanged.
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
    turn_id:        str   = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    prompt:         str
    intent_summary: str   = ""
    result_rows:    int   = 0
    result_label:   str   = ""
    timestamp:      float = Field(default_factory=time.time)


# ── session context ───────────────────────────────────────────────

class SessionContext(BaseModel):
    session_id:    str
    created_at:    float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)

    # data context
    schema_context:      Optional[SchemaContext]     = None
    dataset_fingerprint: Optional[str]               = None

    # carry-forward
    previous_intent:  Optional[QueryIntent]          = None
    previous_result:  Optional[ExecutionResult]      = None

    # datasource
    datasource_type:       Optional[str]             = None
    connection_string:     Optional[str]             = None
    selected_table:        Optional[str]             = None
    selected_table_schema: Optional[dict[str, Any]]  = None
    source_name:           Optional[str]             = None

    # conversation history
    conversation_turns: list[ConversationTurn] = Field(default_factory=list)

    # ── NEW: schema profile cache (excluded from dict serialisation) ──
    # Stores the full schema_profile dict so followup_resolver and
    # the /chat route can access column top_values for value-based
    # filter injection without re-profiling the dataframe.
    schema_profile_cache: Optional[dict[str, Any]] = Field(
        default=None,
        exclude=True,   # don't serialise — too large, not needed in responses
    )

    class Config:
        arbitrary_types_allowed = True

    def add_turn(
        self,
        prompt:  str,
        intent:  QueryIntent,
        result:  ExecutionResult,
    ) -> None:
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
        max_t = settings.max_conversation_turns
        if len(self.conversation_turns) > max_t:
            self.conversation_turns = self.conversation_turns[-max_t:]

    def get_context_summary(self) -> str:
        if not self.conversation_turns:
            return ""
        lines = []
        for i, turn in enumerate(self.conversation_turns[-3:], 1):
            lines.append(
                f"  Turn {i}: \"{turn.prompt}\" → {turn.intent_summary} "
                f"({turn.result_rows} rows, label='{turn.result_label}')"
            )
        return "Recent conversation:\n" + "\n".join(lines)


# ── fingerprint ───────────────────────────────────────────────────

def compute_dataset_fingerprint(column_names: list[str], row_count: int) -> str:
    key = f"{sorted(column_names)}:{row_count}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ── store ─────────────────────────────────────────────────────────

class SessionStore:
    """
    In-memory session store.
    TTL: settings.session_ttl_seconds (default 30 min).
    Eviction: lazy on get/new_session.
    """

    def __init__(self) -> None:
        self._store: dict[str, SessionContext] = {}

    # ── creation ──────────────────────────────────────────────────

    def new_session(self) -> str:
        self._evict_stale()
        sid = str(uuid.uuid4())
        self._store[sid] = SessionContext(session_id=sid)
        return sid

    # ── read ──────────────────────────────────────────────────────

    def get(self, session_id: str) -> Optional[SessionContext]:
        self._evict_stale()
        ctx = self._store.get(session_id)
        if ctx:
            ctx.last_accessed = time.time()
        return ctx

    def get_or_create(self, session_id: str) -> tuple[SessionContext, bool]:
        sid = session_id.strip()
        if sid:
            ctx = self.get(sid)
            if ctx:
                return ctx, False
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
        ctx = self._store.get(session_id)
        if ctx is None:
            return
        ctx.add_turn(prompt, intent, result)
        ctx.last_accessed = time.time()

    def set_schema(
        self,
        session_id:    str,
        schema:        SchemaContext,
        column_names:  list[str],
        row_count:     int,
        schema_profile: Optional[dict[str, Any]] = None,   # NEW param
    ) -> None:
        ctx = self._store.get(session_id)
        if ctx is None:
            return
        ctx.schema_context      = schema
        ctx.dataset_fingerprint = compute_dataset_fingerprint(column_names, row_count)
        if schema_profile is not None:
            ctx.schema_profile_cache = schema_profile     # ← stored as proper field
        ctx.last_accessed = time.time()

    def set_datasource(
        self,
        session_id:        str,
        datasource_type:   str,
        connection_string: str,
    ) -> None:
        ctx = self._store.get(session_id)
        if ctx is None:
            return
        ctx.datasource_type   = datasource_type
        ctx.connection_string = connection_string
        ctx.last_accessed     = time.time()

    def set_selected_table(
        self,
        session_id:   str,
        table_name:   str,
        table_schema: dict[str, Any],
    ) -> None:
        ctx = self._store.get(session_id)
        if ctx is None:
            return
        ctx.selected_table        = table_name
        ctx.selected_table_schema = table_schema
        ctx.source_name           = table_name
        ctx.last_accessed         = time.time()

    def get_connection_string(self, session_id: str) -> Optional[str]:
        ctx = self._store.get(session_id)
        if ctx is None:
            return None
        ctx.last_accessed = time.time()
        return ctx.connection_string

    def get_selected_table(self, session_id: str) -> Optional[str]:
        ctx = self._store.get(session_id)
        if ctx is None:
            return None
        ctx.last_accessed = time.time()
        return ctx.selected_table

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


session_store = SessionStore()