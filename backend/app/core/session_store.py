"""
app/core/session_store.py
══════════════════════════════════════════════════════════════════════
In-memory session store for iterative analysis context.

Stores: schema, previous intent, previous result, conversation history.
TTL: 30 minutes. Evicts stale sessions on each access.

Usage:
    from app.core.session_store import session_store

    # save
    session_store.save(session_id, context)

    # retrieve
    ctx = session_store.get(session_id)   # None if expired or unknown

    # create new
    session_id = session_store.new_session()
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from app.core.models import SessionContext

_TTL_SECONDS = 30 * 60  # 30 minutes


class SessionStore:
    def __init__(self) -> None:
        self._store: dict[str, SessionContext] = {}

    def new_session(self) -> str:
        session_id = str(uuid.uuid4())
        self._store[session_id] = SessionContext(
            session_id=session_id,
            created_at=time.time(),
            last_accessed=time.time(),
        )
        return session_id

    def get(self, session_id: str) -> Optional[SessionContext]:
        self._evict_stale()
        ctx = self._store.get(session_id)
        if ctx:
            ctx.last_accessed = time.time()
        return ctx

    def save(self, session_id: str, ctx: SessionContext) -> None:
        ctx.last_accessed = time.time()
        self._store[session_id] = ctx

    def update(self, session_id: str, **kwargs: Any) -> None:
        ctx = self._store.get(session_id)
        if ctx is None:
            ctx = SessionContext(
                session_id=session_id,
                created_at=time.time(),
                last_accessed=time.time(),
            )
        for k, v in kwargs.items():
            setattr(ctx, k, v)
        ctx.last_accessed = time.time()
        self._store[session_id] = ctx

    def _evict_stale(self) -> None:
        now = time.time()
        stale = [
            sid for sid, ctx in self._store.items()
            if now - ctx.last_accessed > _TTL_SECONDS
        ]
        for sid in stale:
            del self._store[sid]

    def __len__(self) -> int:
        return len(self._store)


# module-level singleton
session_store = SessionStore()