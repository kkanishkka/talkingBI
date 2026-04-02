"""
app/core/config.py
══════════════════════════════════════════════════════════════════════
Centralised configuration.
All environment variables are read ONCE here — never scattered via
os.getenv() across services.

Usage:
    from app.core.config import settings
    if settings.openai_api_key: ...
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
from typing import Optional


class Settings:
    # ── LLM ───────────────────────────────────────────────────────
    openai_api_key:    str           = os.getenv("OPENAI_API_KEY", "")
    openai_api_base:   Optional[str] = os.getenv("OPENAI_API_BASE")
    openai_model:      str           = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    anthropic_api_key: str           = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model:   str           = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
    llm_max_tokens:    int           = int(os.getenv("LLM_MAX_TOKENS", "1200"))
    llm_temperature:   float         = float(os.getenv("LLM_TEMPERATURE", "0.0"))

    # ── Session ───────────────────────────────────────────────────
    session_ttl_seconds:   int = int(os.getenv("SESSION_TTL_SECONDS", str(30 * 60)))
    max_conversation_turns: int = int(os.getenv("MAX_CONVERSATION_TURNS", "20"))

    # ── Pipeline ──────────────────────────────────────────────────
    max_df_rows:    int = int(os.getenv("MAX_DF_ROWS", "500000"))
    sample_rows:    int = int(os.getenv("SAMPLE_ROWS", "100000"))
    max_retries:    int = int(os.getenv("MAX_RETRIES", "2"))
    overview_charts: int = int(os.getenv("OVERVIEW_CHARTS", "3"))

    # ── Upload limits ─────────────────────────────────────────────
    max_upload_mb:  int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    max_columns:    int = int(os.getenv("MAX_COLUMNS", "200"))

    # ── CORS ──────────────────────────────────────────────────────
    allowed_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
        ).split(",")
        if o.strip()
    ]

    @property
    def llm_available(self) -> bool:
        return bool(self.openai_api_key or self.anthropic_api_key)


settings = Settings()
