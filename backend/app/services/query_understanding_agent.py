"""
app/services/query_understanding_agent.py
══════════════════════════════════════════════════════════════════════
Agent 1: Query Understander — v2 (schema-agnostic)

v2 changes:
  ① LLM system prompt hardened to be schema-driven:
     - Instructs model to use ONLY column names from the provided schema
     - Adds explicit "do not invent column names" rule
     - Adds multi_metrics[] field so the LLM can signal multiple
       requested metrics to the planner layer

  ② Rule-based path uses only token-overlap against actual schema
     columns — no hardcoded alias dictionaries.

  ③ _match_columns_from_schema() replaces old static _METRIC_FIELD_ALIASES.
     It works by comparing query tokens to column name tokens.

  ④ Fallback metric/dimension selection uses semantic_hint priority
     from the live schema (currency → count_field → score → none),
     not a fixed list of column names.

Works identically for:
  - ecommerce (sales, category, sub_category)
  - healthcare (diagnosis, department, los)
  - finance (amount, account_type, region)
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
from app.services.semantic_classifier import (
    find_best_dimension, find_best_metric, find_best_target,
)

import logging
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# LLM prompt — schema-driven, domain-neutral
# ═══════════════════════════════════════════════════════════════════

_SYSTEM = """\
You are a BI query understanding engine for a schema-agnostic analytics system.
Given a user question and the ACTUAL dataset schema, output ONLY a valid JSON object.

{
  "question_type": "ranking"|"comparison"|"trend"|"distribution"|"aggregation"|"correlation"|"filtered_lookup"|"overview",
  "metric": "rate"|"count"|"sum"|"mean"|"median"|"max"|"min",
  "multi_metrics": ["<col1>", "<col2>"],
  "primary_dimension": "<exact column name from schema, or null>",
  "secondary_dimension": "<exact column name from schema, or null>",
  "target_variable": "<exact column name from schema, or null>",
  "rate_value": "<positive class value or null>",
  "filters": [{"column":"<exact col>", "operator":"==|!=|>|<|>=|<=", "value":"..."}],
  "time_column": "<exact column name from schema, or null>",
  "time_grain": "D"|"W"|"M"|"Q"|"Y"|null,
  "sort_direction": "asc"|"desc",
  "top_n": <integer or null>,
  "requested_kpis": ["<KPI phrases>"],
  "color_schema": "<color/theme or null>",
  "assumptions": ["<inference made>"]
}

CRITICAL RULES:
1. Use ONLY column names from the schema provided below. NEVER invent column names.
2. multi_metrics: list all metric columns the user explicitly wants computed.
   If "analyze X and Y" → multi_metrics: ["X_col", "Y_col"] (exact schema names).
   If only one metric → multi_metrics: ["col"].
3. primary_dimension: only if user says "by X", "per X", "across X", "for each X",
   or mentions a dimension column name. Otherwise null.
4. question_type:
   - No dimension + scalar → "aggregation"
   - "by X" + sort/rank → "ranking"
   - "over time" / "monthly" → "trend"
   - "analyze" / "compare" / "dashboard" → "comparison" or "overview"
5. target_variable: the metric column to aggregate for sum/mean/max/min.
6. Do not guess column names. If a column the user mentions is not in the schema,
   leave the field null and note it in assumptions.
7. Output ONLY valid JSON. No markdown. No explanation.
8. Extract any color or theme preferences (e.g. 'dark blue', 'red theme') into 'color_schema' if mentioned.
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
    return f"User question: {prompt}\n\nDataset schema:\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Rule-based keyword tables (metric type & question type)
# These are LANGUAGE patterns, not domain column names.
# ═══════════════════════════════════════════════════════════════════

_METRIC_KEYWORDS: dict[str, list[str]] = {
    MetricType.rate:   [
        "rate", "ratio", "conversion", "percentage", "likelihood",
        "probability", "how likely", "tends to", "more likely",
        "performs best", "most likely", "proportion",
    ],
    MetricType.count:  ["count", "how many", "number of", "frequency", "occurrences", "volume"],
    MetricType.sum:    ["total", "sum", "aggregate", "gross", "overall"],
    MetricType.mean:   ["average", "mean", "avg", "typical", "aov"],
    MetricType.median: ["median", "middle"],
    MetricType.max:    ["maximum", "max", "peak", "highest value"],
    MetricType.min:    ["minimum", "min", "lowest value", "floor"],
}

_QTYPE_KEYWORDS: dict[str, list[str]] = {
    QuestionType.ranking:      ["highest", "lowest", "top", "bottom", "best", "worst",
                                 "rank", "most", "least", "who leads", "leading"],
    QuestionType.trend:        ["trend", "over time", "time series", "monthly", "daily",
                                 "quarterly", "yearly", "growth", "decline", "change over",
                                 "weekly", "annual"],
    QuestionType.comparison:   ["compare", "comparison", "versus", "vs", "across",
                                 "between", "differ", "difference"],
    QuestionType.distribution: ["distribution", "spread", "breakdown", "split",
                                 "histogram", "how distributed", "what share"],
    QuestionType.correlation:  ["correlation", "relationship", "impact",
                                 "association", "affect", "influence"],
    QuestionType.aggregation:  ["total", "sum of", "average", "overall",
                                 "what is the", "how much"],
    QuestionType.filtered_lookup: ["where", "filter", "only", "just",
                                    "among", "within", "show me for"],
}

_DIMENSION_PHRASES = re.compile(
    r"\bby\b|\bper\b|\bacross\b|\bfor each\b|\bgroup(?:ed)?\s+by\b"
    r"|\bbreak\s+down\b|\bbreakdown\s+by\b|\bwith\s+respect\s+to\b",
    re.I,
)


# ═══════════════════════════════════════════════════════════════════
# Schema-driven column matching (NO hardcoded domain names)
# ═══════════════════════════════════════════════════════════════════

def _tokenise(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _col_tokens(col_name: str) -> set[str]:
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", col_name)
    return set(re.findall(r"[a-z0-9]+", parts.lower()))


def _query_mentions_col(query_tokens: list[str], col_name: str) -> bool:
    return bool(_col_tokens(col_name) & set(query_tokens))


def _match_columns_from_schema(
    prompt:         str,
    schema_profile: dict[str, Any],
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Schema-driven column extraction.
    Returns (primary_dim, secondary_dim, target_var, time_col).

    All matching is against ACTUAL column names in the live schema.
    No alias dictionaries, no hardcoded domain terms.
    """
    query_tokens = _tokenise(prompt)
    columns      = schema_profile.get("columns", [])
    low          = prompt.lower()

    dims         = [c for c in columns if c["role"] == "dimension"
                    and c.get("semantic_hint") not in ("likely_id",)]
    dates        = [c for c in columns if c["role"] == "date"]
    metrics_cols = [c for c in columns if c["role"] == "metric"]
    targets      = [c for c in columns if c.get("semantic_hint") == SemanticHint.likely_target.value]

    primary_dim: Optional[str] = None
    second_dim:  Optional[str] = None
    target_var:  Optional[str] = None
    time_col:    Optional[str] = None

    # ── Dimension: only when explicitly requested ─────────────────
    if _DIMENSION_PHRASES.search(prompt):
        # Find first dimension col mentioned after by/per/across
        m = re.search(
            r"\b(?:by|per|across|for each|breakdown by|group(?:ed)?\s+by)\s+([a-z0-9_ ]+)",
            low,
        )
        if m:
            phrase_toks = set(_tokenise(m.group(1).strip()))
            for col in dims:
                if _col_tokens(col["name"]) & phrase_toks:
                    primary_dim = col["name"]
                    break
        if primary_dim is None:
            for col in dims:
                if _query_mentions_col(query_tokens, col["name"]):
                    primary_dim = col["name"]
                    break
    else:
        # No explicit grouping phrase — still allow direct col name mention
        for col in dims:
            if _query_mentions_col(query_tokens, col["name"]):
                primary_dim = col["name"]
                break

    # ── Secondary dimension ───────────────────────────────────────
    if primary_dim:
        for col in dims:
            if col["name"] != primary_dim and _query_mentions_col(query_tokens, col["name"]):
                second_dim = col["name"]
                break

    # ── Target variable for binary metrics (rate) ─────────────────
    for col in targets:
        if _query_mentions_col(query_tokens, col["name"]):
            target_var = col["name"]
            break

    # ── Target variable for numeric metrics (sum/mean/…) ──────────
    if target_var is None:
        for col in metrics_cols:
            if _query_mentions_col(query_tokens, col["name"]):
                target_var = col["name"]
                break

    # ── Time column ───────────────────────────────────────────────
    time_keywords = ["trend", "over time", "monthly", "daily", "quarterly",
                     "yearly", "week", "annual", "time series"]
    if any(kw in low for kw in time_keywords) and dates:
        for col in dates:
            if _query_mentions_col(query_tokens, col["name"]):
                time_col = col["name"]
                break
        if time_col is None:
            time_col = dates[0]["name"]

    return primary_dim, second_dim, target_var, time_col


# ═══════════════════════════════════════════════════════════════════
# Scalar detectors (language-level, not domain-level)
# ═══════════════════════════════════════════════════════════════════

def _detect_metric(text: str) -> MetricType:
    low = text.lower()
    for metric, keywords in _METRIC_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return MetricType(metric)
    return MetricType.count


def _detect_question_type(text: str, metric: MetricType, has_dimension: bool) -> QuestionType:
    low = text.lower()
    for qtype, keywords in _QTYPE_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return QuestionType(qtype)
    if metric == MetricType.rate:
        return QuestionType.ranking
    if metric in (MetricType.sum, MetricType.mean, MetricType.median,
                  MetricType.max, MetricType.min) and not has_dimension:
        return QuestionType.aggregation
    return QuestionType.distribution


def _detect_sort_direction(text: str) -> str:
    if any(kw in text.lower() for kw in ["lowest", "worst", "least", "ascending", "bottom"]):
        return "asc"
    return "desc"


def _detect_top_n(text: str) -> Optional[int]:
    m = re.search(r"\btop[\s-]?(\d+)\b", text.lower())
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*(highest|lowest|best|worst)\b", text.lower())
    if m:
        return int(m.group(1))
    if re.search(r"\btop\b", text.lower()):
        return 10
    return None


def _detect_time_grain(text: str) -> Optional[str]:
    low = text.lower()
    if "daily"     in low or "day"     in low: return "D"
    if "weekly"    in low or "week"    in low: return "W"
    if "monthly"   in low or "month"   in low: return "M"
    if "quarterly" in low or "quarter" in low: return "Q"
    if "yearly"    in low or "annual"  in low or "year" in low: return "Y"
    return None


_POSITIVE_CLASS_VALUES = frozenset({
    "yes", "true", "1", "1.0", "success", "subscribed",
    "converted", "approved", "pass", "y",
})


def _find_rate_value(
    target_col: str,
    schema_profile: dict[str, Any],
) -> tuple[str, str]:
    for col in schema_profile.get("columns", []):
        if col["name"] != target_col:
            continue
        top = col.get("top_values", [])
        if not top:
            return "yes", f"Positive class for '{target_col}' assumed 'yes'"
        for tv in top:
            if str(tv["value"]).lower() in _POSITIVE_CLASS_VALUES:
                return str(tv["value"]), (
                    f"Positive class for '{target_col}' = '{tv['value']}'"
                )
        if len(top) >= 2:
            pos = min(top, key=lambda x: x["count"])
            return str(pos["value"]), (
                f"Positive class for '{target_col}' = '{pos['value']}' "
                f"(least frequent — override if incorrect)"
            )
        return str(top[0]["value"]), f"Only one value in '{target_col}'"
    return "yes", f"Positive class for '{target_col}' assumed 'yes'"


# ═══════════════════════════════════════════════════════════════════
# Rule-based path
# ═══════════════════════════════════════════════════════════════════

def _rule_based_understand(
    prompt:         str,
    schema_profile: dict[str, Any],
) -> QueryIntent:
    primary_dim, second_dim, target_var, time_col = \
        _match_columns_from_schema(prompt, schema_profile)

    has_dimension = primary_dim is not None
    metric        = _detect_metric(prompt)
    question_type = _detect_question_type(prompt, metric, has_dimension)
    sort_direction = _detect_sort_direction(prompt)
    top_n          = _detect_top_n(prompt)
    time_grain     = _detect_time_grain(prompt)
    
    color_match = re.search(r"\b(red|blue|green|dark|light|pastel|monochrome)\s*(?:theme|schema|colors?|palette)?\b", prompt.lower())
    color_schema = color_match.group(1) if color_match else None

    assumptions: list[str] = []
    rate_value:  Optional[str] = None
    columns      = schema_profile.get("columns", [])
    targets      = [c for c in columns if c.get("semantic_hint") == SemanticHint.likely_target.value]

    # Rate requires a binary target column
    if metric == MetricType.rate:
        if target_var is None and targets:
            target_var = targets[0]["name"]
            assumptions.append(
                f"Rate metric — using binary column '{target_var}' as outcome"
            )
        if target_var:
            rate_value, assumption = _find_rate_value(target_var, schema_profile)
            assumptions.append(assumption)

    # For sum/mean: pick best metric column if not already found
    if metric in (MetricType.sum, MetricType.mean, MetricType.median,
                  MetricType.max, MetricType.min) and target_var is None:
        best = find_best_metric(columns)
        if best:
            target_var = best
            assumptions.append(
                f"No metric column explicitly mentioned — using '{target_var}' "
                f"(best numeric column by semantic hint)"
            )
            
    # Fix default metric for extracted targets: if no explicit count keywords are present, 
    # but we found a target variable that is a metric, default to sum instead of count
    count_kws = _METRIC_KEYWORDS[MetricType.count]
    if metric == MetricType.count and target_var is not None:
        if not any(kw in prompt.lower() for kw in count_kws):
            metric = MetricType.sum
            assumptions.append(f"Numeric target extracted without keyword, defaulting to sum instead of count")

    # Trend without time column → downgrade
    if question_type == QuestionType.trend and not time_col:
        question_type = QuestionType.aggregation if not has_dimension else QuestionType.comparison
        assumptions.append("No date column found — switched trend to aggregation/comparison")

    # Scalar KPI: no dimension + aggregatable metric
    if not has_dimension and metric in (MetricType.sum, MetricType.mean,
                                         MetricType.median, MetricType.max,
                                         MetricType.min, MetricType.count):
        if question_type not in (QuestionType.aggregation, QuestionType.trend,
                                  QuestionType.correlation):
            question_type = QuestionType.aggregation
            assumptions.append("No grouping dimension — returning KPI aggregate")

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
        color_schema=        color_schema,
        filters=             [],
        time_column=         time_col if question_type == QuestionType.trend else None,
        time_grain=          time_grain,
        sort_direction=      sort_direction,
        top_n=               top_n,
        requested_kpis=      list(set(kpis)),
        raw_prompt=          prompt,
        assumptions=         assumptions,
    )


# ═══════════════════════════════════════════════════════════════════
# LLM path
# ═══════════════════════════════════════════════════════════════════

def _llm_understand(
    prompt:         str,
    schema_profile: dict[str, Any],
) -> Optional[QueryIntent]:
    if not llm_client.available:
        return None

    msg  = _build_user_message(prompt, schema_profile)
    data = llm_client.complete_json(_SYSTEM, msg, temperature=0.0)
    if not data:
        return None

    try:
        # Validate all column references against actual schema
        col_names = {c["name"] for c in schema_profile.get("columns", [])}

        def validated_col(name: Any) -> Optional[str]:
            if name and name in col_names:
                return name
            if name:
                logger.warning("LLM returned unknown column '%s' — ignoring", name)
            return None
            
        def validated_metric_target(name: Any) -> Optional[str]:
            valid = validated_col(name)
            if valid:
                for c in schema_profile.get("columns", []):
                    if c["name"] == valid and c.get("role") == "metric":
                        return valid
            return None

        filters = [
            FilterSpec(
                column=   f["column"],
                operator= f.get("operator", "=="),
                value=    f["value"],
            )
            for f in data.get("filters", [])
            if isinstance(f, dict) and "column" in f and f["column"] in col_names
        ]

        # Use multi_metrics if provided to enrich requested_kpis
        multi_metrics  = data.get("multi_metrics", [])
        requested_kpis = data.get("requested_kpis", [])
        if multi_metrics:
            requested_kpis = list(set(requested_kpis + multi_metrics))

        return QueryIntent(
            question_type=       QuestionType(data.get("question_type", "overview")),
            metric=              MetricType(data.get("metric", "count")),
            primary_dimension=   validated_col(data.get("primary_dimension")),
            secondary_dimension= validated_col(data.get("secondary_dimension")),
            target_variable=     validated_metric_target(data.get("target_variable")),
            rate_value=          data.get("rate_value"),
            color_schema=        data.get("color_schema"),
            filters=             filters,
            time_column=         validated_col(data.get("time_column")),
            time_grain=          data.get("time_grain"),
            sort_direction=      data.get("sort_direction", "desc"),
            top_n=               data.get("top_n"),
            requested_kpis=      requested_kpis,
            raw_prompt=          prompt,
            assumptions=         data.get("assumptions", []),
        )

    except Exception as exc:
        logger.warning("QueryUnderstanding: LLM parse failed: %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def understand_query(
    user_prompt:    str,
    schema_profile: dict[str, Any],
) -> QueryIntent:
    """
    Convert a user prompt + schema profile → QueryIntent.
    Schema-agnostic: works for any table with any column names.
    LLM path first; rule-based fallback on any failure.
    """
    generic = {"give me a complete overview", "overview", "dashboard", "show me everything"}
    if user_prompt.lower().strip() in generic or len(user_prompt.strip()) < 8:
        return QueryIntent(
            question_type= QuestionType.overview,
            metric=        MetricType.count,
            raw_prompt=    user_prompt,
            assumptions=   ["Generic overview — showing dataset summary"],
        )

    intent = _llm_understand(user_prompt, schema_profile)
    if intent is not None:
        logger.info(
            "QueryUnderstanding: LLM path, type=%s metric=%s dim=%s target=%s",
            intent.question_type, intent.metric,
            intent.primary_dimension, intent.target_variable,
        )
        return intent

    logger.info("QueryUnderstanding: rule-based fallback")
    return _rule_based_understand(user_prompt, schema_profile)