"""
app/services/query_understanding_agent.py
══════════════════════════════════════════════════════════════════════
Agent 1: Query Understander

Converts a raw user prompt + SchemaContext → QueryIntent.

Primary path:   LLM call → structured JSON → QueryIntent
Fallback path:  rule-based extractor (extended keyword matching,
                semantic-hint-aware column selection)

Key improvements over original intent_parser.py:
  - Uses SchemaContext with semantic_hints for smarter column selection
  - Produces assumptions list (exposed in API response)
  - Handles secondary_dimension
  - Detects rate_value (positive class) from top_values
  - Handles natural phrasing: "tends to", "more likely", "performs best"
  - Works identically with or without LLM API key
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.core.llm_client import llm_client
from app.core.models import (
    FilterSpec, InferenceSource, MetricType, QueryIntent,
    QuestionType, SemanticHint,
)
from app.services.semantic_classifier import (
    find_best_dimension, find_best_metric, find_best_target,
)

import logging
logger = logging.getLogger(__name__)


# ── LLM prompt ────────────────────────────────────────────────────

_SYSTEM = """You are a BI query understanding engine.
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
- "subscription rate" / "conversion rate" / "X rate" / "likelihood" / "tends to" / "more likely" → metric="rate"
- "how many" / "count" → metric="count"
- "average" / "mean" → metric="mean"
- "total" / "sum" → metric="sum"
- "highest" / "top" / "best" / "most" / "performs best" → question_type="ranking", sort_direction="desc"
- "lowest" / "worst" / "least" → question_type="ranking", sort_direction="asc"
- "trend" / "over time" / "monthly" / "quarterly" → question_type="trend"
- "compare" / "vs" / "versus" / "between" / "across" → question_type="comparison"
- For rate: target_variable is the binary outcome column (e.g. "y", "subscribed", "converted")
- rate_value: the value that counts as "positive" (e.g. "yes", "1", "success")
- If the user mentions two grouping dimensions, set both primary and secondary
- assumptions must list every inference made (e.g. "Assumed 'y'='yes' as positive class")
- Output ONLY valid JSON. No markdown. No explanation.
"""


def _build_user_message(prompt: str, schema_profile: dict[str, Any]) -> str:
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
    return f"User question: {prompt}\n\nDataset columns:\n" + "\n".join(lines)


# ── rule-based path ───────────────────────────────────────────────

_METRIC_KEYWORDS: dict[str, list[str]] = {
    MetricType.rate:    [
        "rate", "ratio", "conversion", "subscription rate", "percentage",
        "likelihood", "probability", "how likely", "tends to", "more likely",
        "performs best", "most likely", "proportion",
    ],
    MetricType.count:   ["count", "how many", "number of", "frequency", "occurrences"],
    MetricType.sum:     ["total", "sum", "revenue", "sales", "aggregate"],
    MetricType.mean:    ["average", "mean", "avg", "typical"],
    MetricType.median:  ["median", "middle"],
    MetricType.max:     ["maximum", "max", "peak", "highest value"],
    MetricType.min:     ["minimum", "min", "lowest value", "floor"],
}

_QTYPE_KEYWORDS: dict[str, list[str]] = {
    QuestionType.ranking:      [
        "highest", "lowest", "top", "bottom", "best", "worst", "rank",
        "most", "least", "performs best", "who leads", "which has most",
        "which has highest", "which has lowest",
    ],
    QuestionType.trend:        [
        "trend", "over time", "time series", "monthly", "daily", "quarterly",
        "yearly", "growth", "decline", "change over", "evolve",
    ],
    QuestionType.comparison:   [
        "compare", "comparison", "versus", "vs", "across", "between",
        "differ", "difference", "which is higher",
    ],
    QuestionType.distribution: [
        "distribution", "spread", "breakdown", "split", "histogram",
        "how distributed", "how spread",
    ],
    QuestionType.correlation:  [
        "correlation", "relationship", "impact", "association",
        "affect", "influence", "related",
    ],
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
    # if metric is rate and no other qtype matches, default to ranking
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
    low = text.lower()
    if any(kw in low for kw in ["lowest", "worst", "least", "ascending", "bottom"]):
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


def _match_columns_from_query(
    text: str,
    schema_profile: dict[str, Any],
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Returns (primary_dimension, secondary_dimension, target_variable, time_column).
    Uses both explicit name matching and semantic hints.
    """
    low     = text.lower()
    columns = schema_profile.get("columns", [])

    dims     = [c for c in columns if c["role"] == "dimension"]
    metrics  = [c for c in columns if c["role"] == "metric"]
    dates    = [c for c in columns if c["role"] == "date"]
    targets  = [c for c in columns if c.get("semantic_hint") == SemanticHint.likely_target.value]

    primary_dim:  Optional[str] = None
    second_dim:   Optional[str] = None
    target_var:   Optional[str] = None
    time_col:     Optional[str] = None

    # Step 1: explicit column name mentions in query
    mentioned_dims = [c for c in dims if c["name"].lower() in low]
    if len(mentioned_dims) >= 2:
        primary_dim = mentioned_dims[0]["name"]
        second_dim  = mentioned_dims[1]["name"]
    elif len(mentioned_dims) == 1:
        primary_dim = mentioned_dims[0]["name"]

    mentioned_targets = [c for c in targets if c["name"].lower() in low]
    if mentioned_targets:
        target_var = mentioned_targets[0]["name"]

    mentioned_dates = [c for c in dates if c["name"].lower() in low]
    if mentioned_dates:
        time_col = mentioned_dates[0]["name"]

    # Step 2: semantic fallbacks when names not in query
    metric = _detect_metric(text)
    if metric == MetricType.rate and target_var is None and targets:
        target_var = targets[0]["name"]
    if target_var is None and targets:
        target_var = targets[0]["name"]

    if primary_dim is None:
        primary_dim = find_best_dimension(
            columns, exclude=[target_var] if target_var else []
        )

    if time_col is None and dates:
        time_col = dates[0]["name"]

    return primary_dim, second_dim, target_var, time_col


def _find_rate_value(
    target_col: str, schema_profile: dict[str, Any]
) -> tuple[str, str]:
    """
    Returns (rate_value, assumption_string).
    Looks for canonical positive-class values.
    """
    for col in schema_profile.get("columns", []):
        if col["name"] != target_col:
            continue
        top = col.get("top_values", [])
        if not top:
            return "yes", f"Positive class for '{target_col}' assumed to be 'yes' (no top_values available)"

        _POSITIVES = {"yes", "true", "1", "1.0", "success", "subscribed",
                      "converted", "approved", "pass", "y"}
        for tv in top:
            if str(tv["value"]).lower() in _POSITIVES:
                return str(tv["value"]), (
                    f"Positive class for '{target_col}' = '{tv['value']}' "
                    f"(found in top_values, count={tv['count']})"
                )
        # fallback: less frequent value is usually the event
        if len(top) >= 2:
            pos = min(top, key=lambda x: x["count"])
            return str(pos["value"]), (
                f"Positive class for '{target_col}' assumed = '{pos['value']}' "
                f"(least frequent value — override if incorrect)"
            )
        return str(top[0]["value"]), f"Only one value found in '{target_col}'"
    return "yes", f"Positive class for '{target_col}' assumed to be 'yes'"


def _rule_based_understand(
    prompt: str, schema_profile: dict[str, Any]
) -> QueryIntent:
    metric         = _detect_metric(prompt)
    question_type  = _detect_question_type(prompt, metric)
    sort_direction = _detect_sort_direction(prompt)
    top_n          = _detect_top_n(prompt)
    time_grain     = _detect_time_grain(prompt)

    primary_dim, second_dim, target_var, time_col = _match_columns_from_query(
        prompt, schema_profile
    )

    assumptions: list[str] = []
    rate_value:  Optional[str] = None

    if metric == MetricType.rate and target_var:
        rate_value, assumption = _find_rate_value(target_var, schema_profile)
        assumptions.append(assumption)

    if question_type == QuestionType.trend and not time_col:
        question_type = QuestionType.distribution
        assumptions.append("No date column found — switched from trend to distribution analysis")

    if primary_dim:
        assumptions.append(f"Grouped by '{primary_dim}' based on query context")
    if second_dim:
        assumptions.append(f"Secondary grouping by '{second_dim}'")
    if target_var and metric == MetricType.count:
        assumptions.append(f"Counting rows per '{primary_dim}' category")
    if target_var and metric != MetricType.rate:
        assumptions.append(f"Computing {metric} of '{target_var}'")

    kpis = re.findall(
        r"(subscription rate|conversion rate|churn rate|average \w+|total \w+|"
        r"\w+ rate|\w+ ratio)",
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
        sort_direction=      sort_direction,
        top_n=               top_n,
        requested_kpis=      list(set(kpis)),
        raw_prompt=          prompt,
        assumptions=         assumptions,
    )


def _llm_understand(
    prompt: str, schema_profile: dict[str, Any]
) -> Optional[QueryIntent]:
    if not llm_client.available:
        return None

    msg  = _build_user_message(prompt, schema_profile)
    data = llm_client.complete_json(_SYSTEM, msg, temperature=0.0)
    if not data:
        return None

    try:
        filters = [
            FilterSpec(
                column=   f["column"],
                operator= f.get("operator", "=="),
                value=    f["value"],
            )
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
        logger.warning("QueryUnderstanding: failed to parse LLM response: %s", exc)
        return None


# ── public API ────────────────────────────────────────────────────

def understand_query(
    user_prompt:    str,
    schema_profile: dict[str, Any],
) -> QueryIntent:
    """
    Convert a user prompt + schema profile → QueryIntent.
    Always returns a valid intent (falls back to rule-based on any failure).
    """
    # Generic prompts → overview mode, skip heavy parsing
    generic = {"give me a complete overview", "overview", "dashboard", "show me everything"}
    if user_prompt.lower().strip() in generic or len(user_prompt.strip()) < 8:
        return QueryIntent(
            question_type=  QuestionType.overview,
            metric=         MetricType.count,
            raw_prompt=     user_prompt,
            assumptions=    ["Generic overview request — showing dataset summary"],
        )

    intent = _llm_understand(user_prompt, schema_profile)
    if intent is not None:
        logger.info("QueryUnderstanding: LLM path, type=%s metric=%s",
                    intent.question_type, intent.metric)
        return intent

    logger.info("QueryUnderstanding: rule-based fallback")
    return _rule_based_understand(user_prompt, schema_profile)