"""
app/core/llm_client.py
══════════════════════════════════════════════════════════════════════
Single LLM client implementation used by every agent that needs LLM.

Supports: OpenAI-compatible APIs, Anthropic.
Always: returns None on failure so callers fall back to rule-based path.
Never: raises exceptions that would crash the pipeline.

Usage:
    from app.core.llm_client import llm_client
    text = llm_client.complete(system_prompt, user_message, json_mode=True)
    if text is None:
        # use rule-based fallback
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
    """
    Thin wrapper over OpenAI / Anthropic APIs.
    Reads configuration from environment variables:
        OPENAI_API_KEY    — enables OpenAI path
        OPENAI_API_BASE   — override base URL (Azure, local Ollama, etc.)
        OPENAI_MODEL      — default: gpt-4o-mini
        ANTHROPIC_API_KEY — enables Anthropic path
        ANTHROPIC_MODEL   — default: claude-3-haiku-20240307
        LLM_MAX_TOKENS    — default: 1000
        LLM_TEMPERATURE   — default: 0 for structured output, 0.3 for narration
    """

    def __init__(self) -> None:
        self._openai_key    = os.getenv("OPENAI_API_KEY", "")
        self._openai_base   = os.getenv("OPENAI_API_BASE")
        self._openai_model  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
        self._max_tokens    = int(os.getenv("LLM_MAX_TOKENS", "1200"))

    @property
    def available(self) -> bool:
        return bool(self._openai_key or self._anthropic_key)

    def complete(
        self,
        system_prompt: str,
        user_message:  str,
        json_mode:     bool  = True,
        temperature:   float = 0.0,
        max_tokens:    Optional[int] = None,
    ) -> Optional[str]:
        """
        Call the LLM and return raw text response, or None on failure.
        json_mode=True instructs the model to respond with valid JSON only.
        """
        tokens = max_tokens or self._max_tokens

        if self._openai_key:
            return self._openai_complete(
                system_prompt, user_message, json_mode, temperature, tokens
            )
        if self._anthropic_key:
            return self._anthropic_complete(
                system_prompt, user_message, json_mode, temperature, tokens
            )

        logger.debug("LLMClient: no API key configured, returning None")
        return None

    def complete_json(
        self,
        system_prompt: str,
        user_message:  str,
        temperature:   float = 0.0,
    ) -> Optional[dict[str, Any]]:
        """
        Convenience: call LLM, parse JSON, return dict or None.
        Strips markdown fences before parsing.
        """
        raw = self.complete(system_prompt, user_message, json_mode=True, temperature=temperature)
        if raw is None:
            return None
        return self._parse_json(raw)

    # ── OpenAI ────────────────────────────────────────────────────

    def _openai_complete(
        self,
        system: str,
        user:   str,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
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
        system: str,
        user:   str,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
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


# ── module-level singleton ────────────────────────────────────────
llm_client = LLMClient()