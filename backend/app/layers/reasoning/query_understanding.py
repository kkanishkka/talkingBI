"""
app/layers/reasoning/query_understanding.py
══════════════════════════════════════════════════════════════════════
REFACTORED: Session-Aware Query Understanding

Key improvements over original query_understanding_agent.py:
  1. Session context injection — "also by region" resolves against
     previous intent (previous_intent.primary_dimension is preserved)
  2. Follow-up phrase detection — "now break it down", "also show",
     "what about", "compare with" trigger context carry-forward
  3. Conversation context is injected into LLM system prompt
  4. _resolve_followup() merges current partial intent with prior intent
  5. All original LLM + rule-based fallback paths are preserved
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.core.llm_client import llm_client
from app.core.models import (
    FilterSpec, MetricType, QueryIntent,
    QuestionType, SemanticHint,
)
from app.core.session_store import SessionContext
from app.layers.semantic.semantic_classifier import (
    find_best_dimension, find_best_metric, find_best_target,
)

import logging
logger = logging.getLogger(__name__)


# ── Follow-up detection ───────────────────────────────────────────

_FOLLOWUP_PHRASES = [
    "also", "now", "what about", "break it down", "breakdown by",
    "split by", "compare with", "compared to", "versus", "group by",
    "instead", "but only", "filter by", "where", "for those",
    "drill down", "zoom in", "show me more", "additionally",
]


def _is_followup(prompt: str) -> bool:
    low = prompt.lower().strip()
    return any(phrase in low for phrase in _FOLLOWUP_PHRASES)


def _resolve_followup(
    current:  QueryIntent,
    previous: QueryIntent,
) -> QueryIntent:
    """
    Merge current partial intent with previous intent.

    Rules:
    - If current has no primary_dimension, inherit from previous
    - If current has no metric/target, inherit from previous
    - If current has explicit filters, add to previous filters
    - question_type always comes from current (unless it's 'overview')
    """
    merged = current.copy()

    # Inherit dimension if not set in current query
    if merged.primary_dimension is None and previous.primary_dimension:
        merged = merged.copy(update={"primary_dimension": previous.primary_dimension})

    if merged.target_variable is None and previous.target_variable:
        merged = merged.copy(update={"target_variable": previous.target_variable})

    if merged.metric == MetricType.count and previous.metric != MetricType.count:
        # 'count' is often the default — if previous had something specific, keep it
        merged = merged.copy(update={"metric": previous.metric})

    # Accumulate filters (don't replace)
    if previous.filters and not current.filters:
        merged = merged.copy(update={"filters": previous.filters})

    # Carry time column
    if merged.time_column is None and previous.time_column:
        merged = merged.copy(update={"time_column": previous.time_column})

    merged.assumptions.append(
        "Follow-up query — context carried forward from previous analysis."
    )
    return merged


# ── LLM prompt ────────────────────────────────────────────────────

_SYSTEM_BASE = """You are a BI query understanding engine.
Given a user question and dataset schema, output ONLY a valid JSON object with these fields:

{
  "question_type": "ranking"|"comparison"|"trend"|"distribution"|"aggregation"|"correlation"|"filtered_lookup"|"overview",
  "metric": "rate"|"count"|"sum"|"mean"|"median"|"max"|"min"|"ratio"|"percent_change",
  "primary_dimension": "<column name or null>",
  "secondary_dimension": "<column name or null>",
  "target_variable": "<column name or null>",
  "rate_value": "<positive class value or null>",
  "filters": [{"column":"...", "operator":"=="|"!="|">"|"<"|">="|"<=", "value":"..."}],
  "time_column": "<column name or null>",
  "time_grain": "D"|"W"|"M"|"Q"|"Y"|null,
  "sort_direction": "asc"|"desc",
  "top_n": <integer or null>,
  "requested_kpis": ["<list of KPI phrases mentioned by user>"],
  "assumptions": ["<list of inference assumptions made>"]
}

RULES:
- "subscription rate" / "conversion rate" / "X rate" / "likelihood" → metric="rate"
- "how many" / "count" → metric="count"
- "average" / "mean" → metric="mean"
- "total" / "sum" → metric="sum"
- "highest" / "top" / "best" → question_type="ranking", sort_direction="desc"
- "lowest" / "worst" → question_type="ranking", sort_direction="asc"
- "trend" / "over time" / "monthly" → question_type="trend"
- "compare" / "vs" / "versus" / "across" → question_type="comparison"
- For rate: target_variable is the binary outcome column
- assumptions must list every inference made
- Output ONLY valid JSON. No markdown. No explanation.
"""


def _build_llm_message(
    prompt:         str,
    schema_profile: dict[str, Any],
    session_ctx:    Optional[SessionContext] = None,
) -> str:
    cols = schema_profile.get("columns", [])
    lines = []
    for c in cols:
        hint = c.get("semantic_hint", "none")
        tv   = c.get("top_values", [])
        tv_str = f", top_values={[v['value'] for v in tv[:4]]}" if tv else ""
        lines.append(
            f"  {c['name']} (role={c['role']}, dtype={c['dtype']}, "
            f"unique={c['unique_count']}, hint={hint}{tv_str})"
        )

    context_block = ""
    if session_ctx:
        ctx_summary = session_ctx.get_context_summary()
        if ctx_summary:
            context_block = f"\n\n{ctx_summary}\n"

    return (
        f"User question: {prompt}{context_block}\n\n"
        f"Dataset columns:\n" + "\n".join(lines)
    )


# ── Rule-based path (unchanged from original, extended for follow-ups) ──

_METRIC_KEYWORDS: dict[str, list[str]] = {
    MetricType.rate:    ["rate", "ratio", "conversion", "subscription rate", "percentage",
                         "likelihood", "probability", "how likely", "tends to", "more likely",
                         "performs best", "most likely", "proportion"],
    MetricType.count:   ["count", "how many", "number of", "frequency", "occurrences"],
    MetricType.sum:     ["total", "sum", "revenue", "sales", "aggregate"],
    MetricType.mean:    ["average", "mean", "avg", "typical"],
    MetricType.median:  ["median", "middle"],
    MetricType.max:     ["maximum", "max", "peak", "highest value"],
    MetricType.min:     ["minimum", "min", "lowest value", "floor"],
}

_QTYPE_KEYWORDS: dict[str, list[str]] = {
    QuestionType.ranking:      ["highest", "lowest", "top", "bottom", "best", "worst",
                                "rank", "most", "least", "performs best", "who leads"],
    QuestionType.trend:        ["trend", "over time", "time series", "monthly", "daily",
                                "quarterly", "yearly", "growth", "decline", "change over"],
    QuestionType.comparison:   ["compare", "comparison", "versus", "vs", "across",
                                "between", "differ", "difference"],
    QuestionType.distribution: ["distribution", "spread", "breakdown", "split",
                                "histogram", "how distributed"],
    QuestionType.correlation:  ["correlation", "relationship", "impact", "association",
                                "affect", "influence", "related"],
    QuestionType.aggregation:  ["total", "sum of", "average", "overall"],
    QuestionType.filtered_lookup: ["where", "filter", "only", "just", "among", "within"],
}


def _detect_metric(text: str) -> MetricType:
    low = text.lower()
    for metric, keywords in _METRIC_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return MetricType(metric)
    return MetricType.count


def _detect_question_type(text: str, metric: MetricType) -> QuestionType:
    low = text.lower()
    for qtype, keywords in _QTYPE_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return QuestionType(qtype)
    if metric == MetricType.rate:
        return QuestionType.ranking
    return QuestionType.distribution


def _detect_top_n(text: str) -> Optional[int]:
    m = re.search(r"top[\s-]?(\d+)", text.lower())
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(highest|lowest|best|worst)", text.lower())
    if m:
        return int(m.group(1))
    if re.search(r"\btop\b", text.lower()):
        return 10
    return None


def _detect_sort_direction(text: str) -> str:
    if any(kw in text.lower() for kw in ["lowest", "worst", "least", "ascending", "bottom"]):
        return "asc"
    return "desc"


def _detect_time_grain(text: str) -> Optional[str]:
    low = text.lower()
    if "daily"    in low or "day"     in low: return "D"
    if "weekly"   in low or "week"    in low: return "W"
    if "monthly"  in low or "month"   in low: return "M"
    if "quarterly"in low or "quarter" in low: return "Q"
    if "yearly"   in low or "annual"  in low or "year" in low: return "Y"
    return None


def _match_columns(
    text:           str,
    schema_profile: dict[str, Any],
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    low     = text.lower()
    columns = schema_profile.get("columns", [])
    dims    = [c for c in columns if c["role"] == "dimension"]
    dates   = [c for c in columns if c["role"] == "date"]
    targets = [c for c in columns if c.get("semantic_hint") == SemanticHint.likely_target.value]

    primary_dim: Optional[str] = None
    second_dim:  Optional[str] = None
    target_var:  Optional[str] = None
    time_col:    Optional[str] = None

    mentioned_dims = [c for c in dims if c["name"].lower() in low]
    if len(mentioned_dims) >= 2:
        primary_dim, second_dim = mentioned_dims[0]["name"], mentioned_dims[1]["name"]
    elif len(mentioned_dims) == 1:
        primary_dim = mentioned_dims[0]["name"]

    mentioned_targets = [c for c in targets if c["name"].lower() in low]
    if mentioned_targets:
        target_var = mentioned_targets[0]["name"]

    mentioned_dates = [c for c in dates if c["name"].lower() in low]
    if mentioned_dates:
        time_col = mentioned_dates[0]["name"]

    metric = _detect_metric(text)
    if metric == MetricType.rate and target_var is None and targets:
        target_var = targets[0]["name"]
    if target_var is None and targets:
        target_var = targets[0]["name"]
    if primary_dim is None:
        primary_dim = find_best_dimension(columns, exclude=[target_var] if target_var else [])
    if time_col is None and dates:
        time_col = dates[0]["name"]

    return primary_dim, second_dim, target_var, time_col


def _find_rate_value(target_col: str, schema_profile: dict[str, Any]) -> tuple[str, str]:
    for col in schema_profile.get("columns", []):
        if col["name"] != target_col:
            continue
        top = col.get("top_values", [])
        if not top:
            return "yes", f"Positive class for '{target_col}' assumed 'yes' (no top_values)"
        _POSITIVES = {"yes", "true", "1", "1.0", "success", "subscribed",
                      "converted", "approved", "pass", "y"}
        for tv in top:
            if str(tv["value"]).lower() in _POSITIVES:
                return str(tv["value"]), (
                    f"Positive class for '{target_col}' = '{tv['value']}' "
                    f"(found in top_values, count={tv['count']})"
                )
        if len(top) >= 2:
            pos = min(top, key=lambda x: x["count"])
            return str(pos["value"]), (
                f"Positive class for '{target_col}' assumed = '{pos['value']}' "
                f"(least frequent — override if incorrect)"
            )
        return str(top[0]["value"]), f"Only one value found in '{target_col}'"
    return "yes", f"Positive class for '{target_col}' assumed 'yes'"


def _rule_based_understand(prompt: str, schema_profile: dict[str, Any]) -> QueryIntent:
    metric        = _detect_metric(prompt)
    question_type = _detect_question_type(prompt, metric)
    sort_dir      = _detect_sort_direction(prompt)
    top_n         = _detect_top_n(prompt)
    time_grain    = _detect_time_grain(prompt)
    primary_dim, second_dim, target_var, time_col = _match_columns(prompt, schema_profile)

    assumptions: list[str] = []
    rate_value:  Optional[str] = None

    if metric == MetricType.rate and target_var:
        rate_value, assumption = _find_rate_value(target_var, schema_profile)
        assumptions.append(assumption)

    if question_type == QuestionType.trend and not time_col:
        question_type = QuestionType.distribution
        assumptions.append("No date column found — switched trend → distribution")

    if primary_dim:
        assumptions.append(f"Grouped by '{primary_dim}'")
    if second_dim:
        assumptions.append(f"Secondary grouping by '{second_dim}'")

    kpis = re.findall(
        r"(subscription rate|conversion rate|churn rate|average \w+|total \w+|\w+ rate|\w+ ratio)",
        prompt.lower(),
    )

    return QueryIntent(
        question_type=       question_type,
        metric=              metric,
        primary_dimension=   primary_dim,
        secondary_dimension= second_dim,
        target_variable=     target_var,
        rate_value=          rate_value,
        filters=             [],
        time_column=         time_col if question_type == QuestionType.trend else None,
        time_grain=          time_grain,
        sort_direction=      sort_dir,
        top_n=               top_n,
        requested_kpis=      list(set(kpis)),
        raw_prompt=          prompt,
        assumptions=         assumptions,
    )


def _llm_understand(
    prompt:         str,
    schema_profile: dict[str, Any],
    session_ctx:    Optional[SessionContext],
) -> Optional[QueryIntent]:
    if not llm_client.available:
        return None

    # Build system prompt — inject conversation context if available
    system = _SYSTEM_BASE
    if session_ctx:
        ctx_summary = session_ctx.get_context_summary()
        if ctx_summary:
            system += f"\n\n{ctx_summary}"

    msg  = _build_llm_message(prompt, schema_profile, session_ctx)
    data = llm_client.complete_json(system, msg, temperature=0.0)
    if not data:
        return None

    try:
        filters = [
            FilterSpec(column=f["column"], operator=f.get("operator", "=="), value=f["value"])
            for f in data.get("filters", [])
            if isinstance(f, dict) and "column" in f
        ]
        return QueryIntent(
            question_type=       QuestionType(data.get("question_type", "overview")),
            metric=              MetricType(data.get("metric", "count")),
            primary_dimension=   data.get("primary_dimension"),
            secondary_dimension= data.get("secondary_dimension"),
            target_variable=     data.get("target_variable"),
            rate_value=          data.get("rate_value"),
            filters=             filters,
            time_column=         data.get("time_column"),
            time_grain=          data.get("time_grain"),
            sort_direction=      data.get("sort_direction", "desc"),
            top_n=               data.get("top_n"),
            requested_kpis=      data.get("requested_kpis", []),
            raw_prompt=          prompt,
            assumptions=         data.get("assumptions", []),
        )
    except Exception as exc:
        logger.warning("QueryUnderstanding: LLM parse failed: %s", exc)
        return None


# ── Public API ────────────────────────────────────────────────────

def understand_query(
    user_prompt:    str,
    schema_profile: dict[str, Any],
    session_ctx:    Optional[SessionContext] = None,
) -> QueryIntent:
    """
    Convert a user prompt + schema profile → QueryIntent.

    Session context is used to:
    1. Inject conversation history into LLM prompt
    2. Resolve follow-up references via _resolve_followup()
    """
    # Generic overview prompt
    generic = {"give me a complete overview", "overview", "dashboard", "show me everything"}
    if user_prompt.lower().strip() in generic or len(user_prompt.strip()) < 8:
        return QueryIntent(
            question_type=  QuestionType.overview,
            metric=         MetricType.count,
            raw_prompt=     user_prompt,
            assumptions=    ["Generic overview — showing dataset summary"],
        )

    # Detect follow-up
    is_followup = _is_followup(user_prompt) and session_ctx and session_ctx.previous_intent

    # LLM path (session-aware)
    intent = _llm_understand(user_prompt, schema_profile, session_ctx)
    if intent is None:
        logger.info("QueryUnderstanding: rule-based fallback")
        intent = _rule_based_understand(user_prompt, schema_profile)
    else:
        logger.info("QueryUnderstanding: LLM path, type=%s metric=%s",
                    intent.question_type, intent.metric)

    # Resolve follow-up against previous intent
    if is_followup and session_ctx and session_ctx.previous_intent:
        intent = _resolve_followup(intent, session_ctx.previous_intent)
        logger.info("QueryUnderstanding: follow-up resolved")

    return intent
