"""
app/core/llm_client.py
══════════════════════════════════════════════════════════════════════
Single LLM client — v2 (Groq-first)

Priority order:
  1. Groq   — fast, cheap, great for structured JSON (llama-3 / mixtral)
  2. OpenAI — fallback if GROQ_API_KEY not set
  3. Anthropic — last resort

Config (read from environment / .env file):
  GROQ_API_KEY     — enables Groq path  ← NEW
  GROQ_MODEL       — default: llama3-8b-8192
  OPENAI_API_KEY   — enables OpenAI path
  OPENAI_API_BASE  — override base URL
  OPENAI_MODEL     — default: gpt-4o-mini
  ANTHROPIC_API_KEY— enables Anthropic path
  ANTHROPIC_MODEL  — default: claude-3-haiku-20240307
  LLM_MAX_TOKENS   — default: 1200
  LLM_TEMPERATURE  — default: 0.0

Usage:
  from app.core.llm_client import llm_client
  text = llm_client.complete(system, user, json_mode=True)
  # returns None on any failure — callers fall back to rule-based path
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        # Groq
        self._groq_key   = os.getenv("GROQ_API_KEY", "")
        self._groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        # OpenAI
        self._openai_key   = os.getenv("OPENAI_API_KEY", "")
        self._openai_base  = os.getenv("OPENAI_API_BASE")
        self._openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        # Anthropic
        self._anthropic_key   = os.getenv("ANTHROPIC_API_KEY", "")
        self._anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
        # Shared
        self._max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1200"))

    @property
    def available(self) -> bool:
        return bool(self._groq_key or self._openai_key or self._anthropic_key)

    def complete(
        self,
        system_prompt: str,
        user_message:  str,
        json_mode:     bool  = True,
        temperature:   float = 0.0,
        max_tokens:    Optional[int] = None,
    ) -> Optional[str]:
        tokens = max_tokens or self._max_tokens

        if self._groq_key:
            result = self._groq_complete(system_prompt, user_message, json_mode, temperature, tokens)
            if result is not None:
                return result
            logger.warning("LLMClient: Groq failed, trying next provider")

        if self._openai_key:
            result = self._openai_complete(system_prompt, user_message, json_mode, temperature, tokens)
            if result is not None:
                return result
            logger.warning("LLMClient: OpenAI failed, trying next provider")

        if self._anthropic_key:
            return self._anthropic_complete(system_prompt, user_message, json_mode, temperature, tokens)

        logger.debug("LLMClient: no API key configured")
        return None

    def complete_json(
        self,
        system_prompt: str,
        user_message:  str,
        temperature:   float = 0.0,
    ) -> Optional[dict[str, Any]]:
        raw = self.complete(system_prompt, user_message, json_mode=True, temperature=temperature)
        if raw is None:
            return None
        return self._parse_json(raw)

    # ── Groq ──────────────────────────────────────────────────────

    def _groq_complete(
        self,
        system:      str,
        user:        str,
        json_mode:   bool,
        temperature: float,
        max_tokens:  int,
    ) -> Optional[str]:
        try:
            from groq import Groq  # pip install groq
            client = Groq(api_key=self._groq_key)

            messages = [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ]
            params: dict[str, Any] = dict(
                model=self._groq_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            # Groq supports response_format for llama-3 and mixtral models
            if json_mode:
                params["response_format"] = {"type": "json_object"}

            resp = client.chat.completions.create(**params)
            return resp.choices[0].message.content

        except Exception as exc:
            logger.warning("LLMClient Groq call failed: %s", exc)
            return None

    # ── OpenAI ────────────────────────────────────────────────────

    def _openai_complete(
        self,
        system:      str,
        user:        str,
        json_mode:   bool,
        temperature: float,
        max_tokens:  int,
    ) -> Optional[str]:
        try:
            from openai import OpenAI
            kwargs: dict[str, Any] = {}
            if self._openai_base:
                kwargs["base_url"] = self._openai_base
            client = OpenAI(api_key=self._openai_key, **kwargs)

            messages = [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ]
            params: dict[str, Any] = dict(
                model=self._openai_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if json_mode:
                params["response_format"] = {"type": "json_object"}

            resp = client.chat.completions.create(**params)
            return resp.choices[0].message.content

        except Exception as exc:
            logger.warning("LLMClient OpenAI call failed: %s", exc)
            return None

    # ── Anthropic ─────────────────────────────────────────────────

    def _anthropic_complete(
        self,
        system:      str,
        user:        str,
        json_mode:   bool,
        temperature: float,
        max_tokens:  int,
    ) -> Optional[str]:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._anthropic_key)

            if json_mode:
                system = system + "\n\nIMPORTANT: Respond with ONLY a valid JSON object. No markdown, no explanation."

            resp = client.messages.create(
                model=self._anthropic_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text

        except Exception as exc:
            logger.warning("LLMClient Anthropic call failed: %s", exc)
            return None

    # ── JSON parsing ──────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict[str, Any]]:
        try:
            cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLMClient: JSON parse failed: %s\nRaw: %.200s", exc, raw)
            return None


llm_client = LLMClient()