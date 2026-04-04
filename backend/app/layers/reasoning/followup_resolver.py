"""
app/layers/reasoning/followup_resolver.py
══════════════════════════════════════════════════════════════════════
Follow-up Query Resolver

Takes a short, potentially ambiguous follow-up message and resolves
it into a full, self-contained query by merging it with the session's
previous intent context.

Strategy:
  1. Detect follow-up signal words (now, also, only, filter, same, etc.)
  2. Merge carry-forward fields from previous intent
  3. Produce a resolved_prompt that the normal query-understanding
     pipeline can parse as if it were the first message
  4. Inject resolved context directly into the intent if LLM is unavailable

This module is LLM-optional: a deterministic rule-based resolver is
always available as fallback.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.core.models import FilterSpec, QueryIntent
from app.core.session_store import SessionContext

logger = logging.getLogger(__name__)


# ── Signal detection ──────────────────────────────────────────────

_FILTER_SIGNALS     = re.compile(r"\b(only|just|where|filter|for|among|within)\b", re.I)
_METRIC_CHANGE      = re.compile(r"\b(also|compare|show|vs|versus|and)\b", re.I)
_DIMENSION_CHANGE   = re.compile(r"\b(by|per|across|for each|group by)\b", re.I)
_CONTINUATION       = re.compile(r"\b(now|same|that|this|it|again|but)\b", re.I)
_LIMIT_SIGNAL       = re.compile(r"\b(top|bottom|last|first)\s+(\d+)\b", re.I)
_NEGATION           = re.compile(r"\b(except|excluding|not|without)\b", re.I)


def is_followup(message: str, session_ctx: Optional[SessionContext]) -> bool:
    """
    Returns True if the message looks like a follow-up to a previous query.
    Heuristics: short message + continuation signals + session has turns.
    """
    if not session_ctx or not session_ctx.conversation_turns:
        return False
    word_count = len(message.strip().split())
    if word_count > 20:
        return False
    has_signal = bool(
        _FILTER_SIGNALS.search(message)
        or _CONTINUATION.search(message)
        or _METRIC_CHANGE.search(message)
        or _DIMENSION_CHANGE.search(message)
    )
    return has_signal


# ── Deterministic resolver ────────────────────────────────────────

def _extract_new_filter(message: str) -> Optional[QueryFilter]:
    """
    Try to extract a simple equality filter from the follow-up.
    E.g. "only electronics" → QueryFilter(column=<unknown>, value="electronics")
    The column is left as "" and resolved later by query_understanding.
    """
    # "only <value>" or "filter <value>" or "for <value>"
    m = re.search(r"\b(?:only|just|filter|for)\s+([a-zA-Z0-9 _-]+?)(?:\s+(?:orders?|items?|rows?|records?))?$", message, re.I)
    if m:
        val = m.group(1).strip()
        if val and len(val) < 50:
            return QueryFilter(column="", operator="==", value=val)
    return None


def _extract_new_metric(message: str, schema_profile: Optional[dict]) -> Optional[str]:
    """
    If the follow-up mentions a column name that is a metric, return it.
    """
    if not schema_profile:
        return None
    metric_cols = [
        c["name"].lower()
        for c in schema_profile.get("columns", [])
        if c["role"] == "metric"
    ]
    msg_lower = message.lower()
    for col in metric_cols:
        if col in msg_lower:
            return col
    return None


def _extract_new_dimension(message: str, schema_profile: Optional[dict]) -> Optional[str]:
    """
    If the follow-up mentions a column name that is a dimension, return it.
    """
    if not schema_profile:
        return None
    dim_cols = [
        c["name"].lower()
        for c in schema_profile.get("columns", [])
        if c["role"] == "dimension"
    ]
    msg_lower = message.lower()
    for col in dim_cols:
        if col in msg_lower:
            return col
    return None


def _extract_new_limit(message: str) -> Optional[int]:
    m = _LIMIT_SIGNAL.search(message)
    if m:
        return int(m.group(2))
    return None


def build_resolved_prompt(
    message: str,
    session_ctx: SessionContext,
    schema_profile: Optional[dict] = None,
) -> str:
    """
    Merge follow-up message with previous intent context to produce
    a fully self-contained resolved query string.

    The resolved prompt is passed back into the normal
    understand_query() pipeline — no special handling needed downstream.
    """
    prev_turns = session_ctx.conversation_turns
    if not prev_turns:
        return message

    last_turn = prev_turns[-1]
    last_prompt = last_turn.prompt
    last_summary = last_turn.intent_summary

    # If the message is a simple continuation, stitch it onto the last prompt
    filter_match = _extract_new_filter(message)
    new_metric   = _extract_new_metric(message, schema_profile)
    new_dim      = _extract_new_dimension(message, schema_profile)
    new_limit    = _extract_new_limit(message)

    # Build resolved prompt
    base = last_prompt.rstrip(".")

    parts: list[str] = [base]

    if filter_match and filter_match.value:
        parts.append(f"where {filter_match.value}")

    if new_metric and new_metric.lower() not in base.lower():
        parts.append(f"and also show {new_metric}")

    if new_dim and new_dim.lower() not in base.lower():
        parts.append(f"grouped by {new_dim}")

    if new_limit:
        # Replace existing top N or append
        combined = " ".join(parts)
        combined = re.sub(r"\btop\s+\d+\b", f"top {new_limit}", combined, flags=re.I)
        if "top" not in combined.lower():
            combined = f"top {new_limit} " + combined
        logger.info("FollowupResolver: resolved → '%s'", combined)
        return combined

    # If no explicit signals matched but it's a short message, append as context
    if len(parts) == 1 and is_followup(message, session_ctx):
        parts.append(message)

    resolved = " ".join(parts)
    logger.info(
        "FollowupResolver: '%s' → '%s'", message, resolved
    )
    return resolved


def patch_intent_with_followup(
    intent: QueryIntent,
    message: str,
    prev_intent: Optional[QueryIntent],
    schema_profile: Optional[dict] = None,
) -> QueryIntent:
    """
    Post-hoc patch: if query_understanding ran on the resolved prompt but
    still missed carry-forward fields, copy them from prev_intent.

    This is a safety net — query_understanding should pick up most
    context from the resolved prompt, but this ensures nothing is lost.
    """
    if prev_intent is None:
        return intent

    # Carry forward dimension if not re-specified
    if not intent.primary_dimension and prev_intent.primary_dimension:
        intent.primary_dimension = prev_intent.primary_dimension

    # Carry forward metric if not re-specified
    if intent.metric in ("count", None) and prev_intent.metric not in ("count", None):
        intent.metric = prev_intent.metric
        intent.target_variable = prev_intent.target_variable

    # Carry forward existing filters and merge new ones
    existing_keys = {(f.column, f.value) for f in intent.filters}
    for f in prev_intent.filters:
        if (f.column, f.value) not in existing_keys:
            intent.filters.append(f)

    # Carry forward top_n if not specified
    if not intent.top_n and prev_intent.top_n:
        intent.top_n = prev_intent.top_n

    return intent