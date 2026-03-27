"""
app/services/query_understanding_agent.py
════════════════════════════════════════════════════════════════════
Agent 1: Query Understander

Replaces: intent_parser.py

Responsibility:
  Given a raw user query + schema profile, produce a structured
  QueryIntent that captures:
    - question_type  (ranking, comparison, trend, distribution, …)
    - primary_dimension (the column to group by)
    - target_variable   (the column being measured)
    - metric            (rate, count, sum, mean, …)
    - filters           (optional WHERE conditions)
    - sort_direction, top_n

Architecture:
  - Primary path: LLM call with structured JSON prompt
  - Fallback path: rule-based extractor (original intent_parser logic,
    extended with metric detection)
  - The two paths produce the same output schema (QueryIntent)

Usage:
  from app.services.query_understanding_agent import understand_query
  intent = understand_query(user_prompt, schema_profile)
════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── LLM client (lazy import — only needed for primary path) ───────
# Uses the openai SDK which works for OpenAI, Azure, or any compatible
# endpoint. Set OPENAI_API_KEY (or OPENAI_API_BASE for Azure/local).
# If the key is absent the system falls back to rule-based path.

def _llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


def _call_llm(system_prompt: str, user_message: str) -> str | None:
    """
    Call an LLM and return the raw text response.
    Supports OpenAI and Anthropic backends.
    Returns None on failure so the caller can fall back.
    """
    # ── OpenAI / compatible ────────────────────────────────────
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI()
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception as exc:
            logger.warning("OpenAI call failed: %s", exc)
            return None

    # ── Anthropic ──────────────────────────────────────────────
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
                max_tokens=800,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return resp.content[0].text
        except Exception as exc:
            logger.warning("Anthropic call failed: %s", exc)
            return None

    return None


# ── LLM prompt ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a BI query understanding engine. 
Given a user question and dataset schema, output ONLY a valid JSON object 
with exactly these fields:

{
  "question_type": one of ["ranking","comparison","trend","distribution",
                            "aggregation","correlation","filtered_lookup"],
  "primary_dimension": column name to group/split by (string or null),
  "secondary_dimension": second grouping column (string or null),
  "target_variable": column being measured (string or null),
  "metric": one of ["rate","count","sum","mean","median","max","min",
                    "ratio","percent_change"],
  "filter": {"column": "...", "operator": "...", "value": "..."} or null,
  "time_column": column name if trend question (string or null),
  "sort_direction": "asc" or "desc",
  "top_n": integer or null,
  "reasoning": one sentence explaining your interpretation
}

Rules:
- "subscription rate" / "conversion rate" / "X rate" → metric = "rate"
- "how many" / "count of" → metric = "count"
- "average" / "mean" → metric = "mean"
- "total" / "sum" → metric = "sum"
- "highest" / "top" / "best" → question_type = "ranking", sort = "desc"
- "trend" / "over time" / "monthly" → question_type = "trend"
- For rate: target_variable is the binary/flag column (e.g. "y", "subscribed")
- Output ONLY the JSON. No explanation. No markdown.
"""


def _build_user_message(prompt: str, schema_profile: dict[str, Any]) -> str:
    cols = schema_profile.get("columns", [])
    col_summary = "\n".join(
        f"  - {c['name']} ({c['role']}, {c['dtype']}, "
        f"{c['unique_count']} unique"
        + (f", top: {[v['value'] for v in c.get('top_values', [])[:3]]}"
           if c.get('top_values') else "")
        + ")"
        for c in cols
    )
    return f"User question: {prompt}\n\nDataset columns:\n{col_summary}"


# ── rule-based fallback ───────────────────────────────────────────

_METRIC_KEYWORDS: dict[str, list[str]] = {
    "rate":   ["rate", "ratio", "conversion", "subscription rate",
               "percentage", "likelihood", "probability", "how likely"],
    "count":  ["count", "how many", "number of", "frequency"],
    "sum":    ["total", "sum", "revenue", "sales"],
    "mean":   ["average", "mean", "avg"],
    "median": ["median"],
    "max":    ["maximum", "max", "highest value", "peak"],
    "min":    ["minimum", "min", "lowest value"],
}

_QUESTION_TYPE_KEYWORDS: dict[str, list[str]] = {
    "ranking":      ["highest", "lowest", "top", "bottom", "best", "worst",
                     "rank", "ranking", "most", "least"],
    "trend":        ["trend", "over time", "time series", "monthly", "daily",
                     "yearly", "growth", "decline", "change over"],
    "comparison":   ["compare", "comparison", "versus", "vs", "across",
                     "between", "differ"],
    "distribution": ["distribution", "spread", "breakdown", "split",
                     "histogram", "how distributed"],
    "correlation":  ["correlation", "relationship", "impact", "association",
                     "affect", "influence"],
    "aggregation":  ["total", "sum", "average", "mean", "median"],
}


def _detect_metric(text: str) -> str:
    lowered = text.lower()
    for metric, keywords in _METRIC_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return metric
    return "count"


def _detect_question_type(text: str) -> str:
    lowered = text.lower()
    for qtype, keywords in _QUESTION_TYPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return qtype
    return "distribution"


def _match_columns(
    text: str, schema_profile: dict[str, Any]
) -> tuple[str | None, str | None, str | None]:
    """
    Returns (primary_dimension, target_variable, time_column)
    by matching column names against the query text.
    """
    lowered = text.lower()
    cols = schema_profile.get("columns", [])

    dimensions = [c for c in cols if c["role"] == "dimension"]
    metrics    = [c for c in cols if c["role"] == "metric"]
    dates      = [c for c in cols if c["role"] == "date"]

    primary_dim: str | None = None
    target_var:  str | None = None
    time_col:    str | None = None

    # prefer explicitly mentioned columns
    for col in cols:
        if col["name"].lower() in lowered:
            if col["role"] == "dimension" and primary_dim is None:
                primary_dim = col["name"]
            elif col["role"] == "metric" and target_var is None:
                target_var = col["name"]
            elif col["role"] == "date" and time_col is None:
                time_col = col["name"]

    # fallback: pick by role
    # for "rate" questions, look for binary dimension columns as target
    metric = _detect_metric(text)
    if metric == "rate" and target_var is None:
        # binary columns are likely targets (unique_count == 2)
        binary_cols = [
            c for c in dimensions
            if c.get("unique_count", 0) == 2
        ]
        if binary_cols:
            target_var = binary_cols[0]["name"]

    if primary_dim is None and dimensions:
        # pick the dimension most likely mentioned
        primary_dim = dimensions[0]["name"]

    if time_col is None and dates:
        time_col = dates[0]["name"]

    return primary_dim, target_var, time_col


def _rule_based_understand(
    prompt: str, schema_profile: dict[str, Any]
) -> dict[str, Any]:
    """Fallback: rule-based QueryIntent extraction."""
    lowered = prompt.lower()

    question_type  = _detect_question_type(lowered)
    metric         = _detect_metric(lowered)
    primary_dim, target_var, time_col = _match_columns(prompt, schema_profile)

    sort_direction = "desc"
    if "lowest" in lowered or "worst" in lowered or "least" in lowered or "ascending" in lowered:
        sort_direction = "asc"

    top_n: int | None = None
    match = re.search(r"top[- ](\d+)", lowered)
    if match:
        top_n = int(match.group(1))
    elif "top" in lowered:
        top_n = 10

    if question_type == "trend":
        time_col = time_col  # already set above
    else:
        time_col = None

    return {
        "question_type":       question_type,
        "primary_dimension":   primary_dim,
        "secondary_dimension": None,
        "target_variable":     target_var,
        "metric":              metric,
        "filter":              None,
        "time_column":         time_col,
        "sort_direction":      sort_direction,
        "top_n":               top_n,
        "reasoning":           (
            f"Rule-based: detected {question_type} question, "
            f"metric={metric}, dimension={primary_dim}, target={target_var}."
        ),
        "_source": "rule_based",
    }


# ── LLM path ─────────────────────────────────────────────────────

def _llm_understand(
    prompt: str, schema_profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Primary path: call LLM, parse JSON response."""
    if not _llm_available():
        return None

    user_msg  = _build_user_message(prompt, schema_profile)
    raw       = _call_llm(_SYSTEM_PROMPT, user_msg)
    if not raw:
        return None

    try:
        # strip markdown fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        intent  = json.loads(cleaned)
        intent["_source"] = "llm"
        return intent
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse LLM response as JSON: %s\nRaw: %s", exc, raw)
        return None


# ── public API ────────────────────────────────────────────────────

def understand_query(
    user_prompt: str,
    schema_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Main entry point.
    Returns a QueryIntent dict. Always succeeds (falls back to rules).
    """
    intent = _llm_understand(user_prompt, schema_profile)
    if intent is None:
        logger.info("LLM unavailable or failed — using rule-based query understanding.")
        intent = _rule_based_understand(user_prompt, schema_profile)

    # always include the raw prompt for downstream agents
    intent["raw_prompt"]  = user_prompt
    intent["num_visualizations"] = 4
    return intent