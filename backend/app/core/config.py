"""
app/core/config.py
══════════════════════════════════════════════════════════════════════
Centralised configuration — v2 (Groq added)

All environment variables are read ONCE here.

New in v2:
  groq_api_key  — GROQ_API_KEY
  groq_model    — GROQ_MODEL  (default: llama3-8b-8192)

.env file location: project root (same folder as main.py / pyproject.toml).
Load it with python-dotenv before starting the server:
  # pyproject.toml / startup script:
  #   pip install python-dotenv
  #   or add `from dotenv import load_dotenv; load_dotenv()` to main.py

Usage:
  from app.core.config import settings
  if settings.groq_api_key: ...
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
from typing import Optional

# Load .env automatically if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on system env vars


class Settings:
    # ── Groq (primary LLM) ───────────────────────────────────────
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model:   str = os.getenv("GROQ_MODEL", "llama3-8b-8192")

    # ── OpenAI (fallback) ────────────────────────────────────────
    openai_api_key:    str           = os.getenv("OPENAI_API_KEY", "")
    openai_api_base:   Optional[str] = os.getenv("OPENAI_API_BASE")
    openai_model:      str           = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # ── Anthropic (last resort) ──────────────────────────────────
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model:   str = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

    # ── Shared LLM ────────────────────────────────────────────────
    llm_max_tokens:  int   = int(os.getenv("LLM_MAX_TOKENS", "1200"))
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))

    # ── Session ───────────────────────────────────────────────────
    session_ttl_seconds:    int = int(os.getenv("SESSION_TTL_SECONDS", str(30 * 60)))
    max_conversation_turns: int = int(os.getenv("MAX_CONVERSATION_TURNS", "20"))

    # ── Pipeline ──────────────────────────────────────────────────
    max_df_rows:    int = int(os.getenv("MAX_DF_ROWS", "500000"))
    sample_rows:    int = int(os.getenv("SAMPLE_ROWS", "100000"))
    max_retries:    int = int(os.getenv("MAX_RETRIES", "2"))
    overview_charts: int = int(os.getenv("OVERVIEW_CHARTS", "3"))

    # ── Upload limits ─────────────────────────────────────────────
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    max_columns:   int = int(os.getenv("MAX_COLUMNS", "200"))

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
        return bool(self.groq_api_key or self.openai_api_key or self.anthropic_api_key)


settings = Settings()