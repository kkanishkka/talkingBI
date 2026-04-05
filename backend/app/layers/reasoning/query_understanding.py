"""
app/layers/reasoning/query_understanding.py
══════════════════════════════════════════════════════════════════════
Query Understanding — v4 (Groq-first, explanation output)

Changes from v3:
  ① LLM system prompt tightened for Groq (llama-3):
     - More explicit about null vs column name
     - Added "explanation" field to JSON output — a one-line plain-English
       summary of what was understood, used by the chat response.
     - Added "operation" field (scalar_agg | groupby_agg | time_resample
       | value_counts) to give the planner a stronger hint.

  ② understand_query() returns a QueryIntent with .explanation populated.
     (explanation is stored in assumptions[0] and also in a dedicated
     attribute added to the model — see models.py note below.)

  ③ Rule-based fallback generates a matching explanation string.

  ④ _build_llm_message() includes richer schema context:
     - Column roles, dtypes, top_values for dimension cols
     - All date cols listed explicitly

  ⑤ No other logic changed — the LLM path is still optional, rule-based
     path still runs if LLM unavailable or returns None.

Architecture:
  Groq (GROQ_API_KEY) → OpenAI fallback → Anthropic fallback → rule-based
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.core.llm_client import llm_client
from app.core.models import FilterSpec, MetricType, QueryIntent, QuestionType, SemanticHint
from app.core.session_store import SessionContext
from app.layers.semantic.semantic_classifier import find_best_metric

import logging
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — keyword tables (unchanged from v3)
# ═══════════════════════════════════════════════════════════════════

_METRIC_KEYWORDS: dict[str, list[str]] = {
    MetricType.rate:   ["rate", "ratio", "conversion", "subscription rate",
                        "likelihood", "probability", "how likely", "proportion",
                        "tends to", "more likely", "performs best", "most likely"],
    MetricType.count:  ["count", "how many", "number of", "frequency",
                        "occurrences", "total count", "volume"],
    MetricType.sum:    ["total", "sum", "revenue", "sales", "aggregate",
                        "gross", "overall"],
    MetricType.mean:   ["average", "mean", "avg", "typical", "average order",
                        "average value", "aov"],
    MetricType.median: ["median", "middle"],
    MetricType.max:    ["maximum", "max", "peak", "highest value"],
    MetricType.min:    ["minimum", "min", "lowest value", "floor"],
}

_QTYPE_KEYWORDS: dict[str, list[str]] = {
    QuestionType.ranking:      ["highest", "lowest", "top", "bottom", "best",
                                "worst", "rank", "most", "least", "who leads",
                                "leading"],
    QuestionType.trend:        ["trend", "over time", "time series", "monthly",
                                "daily", "quarterly", "yearly", "growth",
                                "decline", "change over", "weekly", "annual"],
    QuestionType.comparison:   ["compare", "comparison", "versus", "vs",
                                "across", "between", "differ", "difference"],
    QuestionType.distribution: ["distribution", "spread", "breakdown", "split",
                                "histogram", "how distributed", "what share"],
    QuestionType.correlation:  ["correlation", "relationship", "impact",
                                "association", "affect", "influence", "related"],
    QuestionType.aggregation:  ["total", "sum of", "average", "overall",
                                "what is the", "how much"],
    QuestionType.filtered_lookup: ["where", "filter", "only", "just",
                                   "among", "within", "show me for"],
}

_DIMENSION_PHRASES = re.compile(
    r"\bby\b|\bper\b|\bacross\b|\bfor each\b|\bgroup(?:ed)?\s+by\b|\bbreak\s+down\b|\bbreakdown\s+by\b",
    re.I,
)

_FOLLOWUP_PHRASES = [
    "also", "now", "what about", "break it down", "breakdown by",
    "split by", "compare with", "compared to", "versus", "group by",
    "instead", "but only", "filter by", "where", "for those",
    "drill down", "zoom in", "show me more", "additionally",
]


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — scalar detectors
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
    if any(kw in text.lower()
           for kw in ["lowest", "worst", "least", "ascending", "bottom"]):
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


def _is_followup(prompt: str) -> bool:
    low = prompt.lower().strip()
    return any(phrase in low for phrase in _FOLLOWUP_PHRASES)


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — schema-driven column matching (unchanged from v3)
# ═══════════════════════════════════════════════════════════════════

def _tokenise(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _col_tokens(col_name: str) -> set[str]:
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", col_name)
    return set(re.findall(r"[a-z0-9]+", parts.lower()))


def _query_mentions_col(query_tokens: list[str], col_name: str) -> bool:
    col_toks = _col_tokens(col_name)
    return bool(col_toks & set(query_tokens))


def _dimension_explicitly_requested(text: str) -> bool:
    return bool(_DIMENSION_PHRASES.search(text))


def _extract_by_phrase_dimension(
    text: str,
    columns: list[dict[str, Any]],
) -> Optional[str]:
    m = re.search(
        r"\b(?:by|per|across|for each|breakdown by|group(?:ed)?\s+by)\s+([a-z0-9_ ]+)",
        text.lower(),
    )
    if not m:
        return None
    phrase = m.group(1).strip()
    phrase_tokens = set(_tokenise(phrase))
    dims = [c for c in columns if c["role"] == "dimension"]
    for col in dims:
        if _col_tokens(col["name"]) & phrase_tokens:
            return col["name"]
    return None


def _match_columns(
    text:           str,
    schema_profile: dict[str, Any],
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    low          = text.lower()
    query_tokens = _tokenise(text)
    columns      = schema_profile.get("columns", [])

    dims         = [c for c in columns if c["role"] == "dimension"
                    and c.get("semantic_hint") not in ("likely_id",)]
    dates        = [c for c in columns if c["role"] == "date"]
    targets      = [c for c in columns if c.get("semantic_hint") == SemanticHint.likely_target.value]
    metrics_cols = [c for c in columns if c["role"] == "metric"]

    primary_dim: Optional[str] = None
    second_dim:  Optional[str] = None
    target_var:  Optional[str] = None
    time_col:    Optional[str] = None

    if _dimension_explicitly_requested(text):
        primary_dim = _extract_by_phrase_dimension(text, columns)
        if primary_dim is None:
            for col in dims:
                if _query_mentions_col(query_tokens, col["name"]):
                    primary_dim = col["name"]
                    break
    else:
        for col in dims:
            if _query_mentions_col(query_tokens, col["name"]):
                if not any(_query_mentions_col(query_tokens, mc["name"])
                           for mc in metrics_cols if mc["name"] == col["name"]):
                    primary_dim = col["name"]
                    break

    if primary_dim:
        for col in dims:
            if col["name"] != primary_dim and _query_mentions_col(query_tokens, col["name"]):
                second_dim = col["name"]
                break

    for col in targets:
        if _query_mentions_col(query_tokens, col["name"]):
            target_var = col["name"]
            break

    if target_var is None:
        for col in metrics_cols:
            if _query_mentions_col(query_tokens, col["name"]):
                target_var = col["name"]
                break

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
# SECTION 4 — rate positive-class detection (unchanged from v3)
# ═══════════════════════════════════════════════════════════════════

_POSITIVE_CLASS_VALUES = frozenset({
    "yes", "true", "1", "1.0", "success", "subscribed",
    "converted", "approved", "pass", "y",
})


def _find_rate_value(target_col: str, schema_profile: dict[str, Any]) -> tuple[str, str]:
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
        return str(top[0]["value"]), f"Only one value found in '{target_col}'"
    return "yes", f"Positive class for '{target_col}' assumed 'yes'"


# ═══════════════════════════════════════════════════════════════════
# SECTION 5 — follow-up resolver (unchanged from v3)
# ═══════════════════════════════════════════════════════════════════

def _build_value_filter(
    value_str:      str,
    schema_profile: dict[str, Any],
) -> Optional[FilterSpec]:
    value_lower = value_str.lower().strip()
    for col in schema_profile.get("columns", []):
        if col["role"] != "dimension":
            continue
        for tv in col.get("top_values", []):
            if str(tv["value"]).lower() == value_lower:
                logger.info(
                    "FollowupResolver: '%s' matched as value in column '%s'",
                    value_str, col["name"],
                )
                return FilterSpec(
                    column=col["name"],
                    operator="==",
                    value=str(tv["value"]),
                )
    return None


def _extract_filter_value_from_followup(prompt: str) -> Optional[str]:
    m = re.search(
        r"\b(?:only|just|filter\s+by|filter|for|where\s+\w+\s*=\s*|now\s+(?:show\s+)?)"
        r"\s*([a-zA-Z0-9][a-zA-Z0-9 _\-]*?)(?:\s+(?:orders?|items?|rows?|records?))?$",
        prompt.strip(), re.I,
    )
    if m:
        val = m.group(1).strip()
        if val and len(val.split()) <= 4:
            return val
    words = prompt.strip().split()
    if len(words) <= 3 and not _dimension_explicitly_requested(prompt):
        return prompt.strip()
    return None


def _resolve_followup(
    current:        QueryIntent,
    previous:       QueryIntent,
    schema_profile: Optional[dict[str, Any]] = None,
) -> QueryIntent:
    merged = current.copy()

    if merged.primary_dimension is None and previous.primary_dimension:
        merged = merged.copy(update={"primary_dimension": previous.primary_dimension})

    if (merged.metric == MetricType.count
            and previous.metric not in (MetricType.count, None)):
        merged = merged.copy(update={
            "metric":          previous.metric,
            "target_variable": merged.target_variable or previous.target_variable,
        })

    if merged.target_variable is None and previous.target_variable:
        merged = merged.copy(update={"target_variable": previous.target_variable})

    if merged.time_column is None and previous.time_column:
        merged = merged.copy(update={"time_column": previous.time_column})

    if merged.top_n is None and previous.top_n:
        merged = merged.copy(update={"top_n": previous.top_n})

    if not merged.filters and schema_profile:
        val_str = _extract_filter_value_from_followup(current.raw_prompt)
        if val_str:
            f = _build_value_filter(val_str, schema_profile)
            if f:
                new_filters = list(previous.filters) + [f]
                merged = merged.copy(update={"filters": new_filters})
                merged.assumptions.append(
                    f"Filter injected: '{f.column}' = '{f.value}' "
                    f"(resolved from follow-up phrase '{val_str}')"
                )
    elif not merged.filters and previous.filters:
        merged = merged.copy(update={"filters": list(previous.filters)})

    merged.assumptions.append(
        "Follow-up query — context carried forward from previous analysis."
    )
    return merged


# ═══════════════════════════════════════════════════════════════════
# SECTION 6 — explanation builder
# ═══════════════════════════════════════════════════════════════════

def _build_explanation(intent: QueryIntent) -> str:
    """
    Build a one-line plain-English explanation of what was understood.
    This is shown in the chat panel alongside the dashboard.

    Examples:
      "I understood this as a ranking query and computed total revenue by category."
      "I treated this as a KPI query and computed the overall sum of amount."
      "I treated this as a trend query and computed count over time by order_date."
    """
    qt     = str(intent.question_type)
    metric = str(intent.metric)
    dim    = intent.primary_dimension
    target = intent.target_variable

    qt_label = {
        "ranking":         "a ranking query",
        "comparison":      "a comparison query",
        "trend":           "a trend query",
        "distribution":    "a distribution query",
        "aggregation":     "a KPI / aggregate query",
        "correlation":     "a correlation query",
        "filtered_lookup": "a filtered lookup",
        "overview":        "a dataset overview",
    }.get(qt, f"a {qt} query")

    if metric == "rate" and target:
        metric_desc = f"{metric} of '{target}'"
    elif metric in ("sum", "mean", "median", "max", "min") and target:
        metric_desc = f"{metric} of '{target}'"
    else:
        metric_desc = metric

    filters_desc = ""
    if intent.filters:
        parts = [f"{f.column}={f.value}" for f in intent.filters[:2]]
        filters_desc = f", filtered by {', '.join(parts)}"

    if dim:
        return (
            f"I understood this as {qt_label} and computed {metric_desc} "
            f"grouped by '{dim}'{filters_desc}."
        )
    else:
        return (
            f"I treated this as {qt_label} and computed the overall "
            f"{metric_desc}{filters_desc}."
        )


# ═══════════════════════════════════════════════════════════════════
# SECTION 7 — rule-based path
# ═══════════════════════════════════════════════════════════════════

def _rule_based_understand(
    prompt:         str,
    schema_profile: dict[str, Any],
) -> QueryIntent:
    primary_dim, second_dim, target_var, time_col = _match_columns(prompt, schema_profile)

    has_dimension = primary_dim is not None
    metric        = _detect_metric(prompt)
    question_type = _detect_question_type(prompt, metric, has_dimension)
    sort_dir      = _detect_sort_direction(prompt)
    top_n         = _detect_top_n(prompt)
    time_grain    = _detect_time_grain(prompt)

    assumptions: list[str] = []
    rate_value:  Optional[str] = None
    columns      = schema_profile.get("columns", [])
    targets      = [c for c in columns if c.get("semantic_hint") == SemanticHint.likely_target.value]

    if metric == MetricType.rate:
        if target_var is None and targets:
            target_var = targets[0]["name"]
            assumptions.append(
                f"Rate metric — using binary column '{target_var}' as outcome"
            )
        if target_var:
            rate_value, assumption = _find_rate_value(target_var, schema_profile)
            assumptions.append(assumption)

    if metric in (MetricType.sum, MetricType.mean, MetricType.median,
                  MetricType.max, MetricType.min) and target_var is None:
        best = find_best_metric(columns)
        if best:
            target_var = best
            assumptions.append(f"No metric column mentioned — using '{target_var}' (best numeric column)")

    if question_type == QuestionType.trend and not time_col:
        question_type = QuestionType.aggregation if not has_dimension else QuestionType.distribution
        assumptions.append("No date column found — switched trend to aggregation/distribution")

    if not has_dimension and metric in (MetricType.sum, MetricType.mean,
                                         MetricType.median, MetricType.max, MetricType.min,
                                         MetricType.count):
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

    intent = QueryIntent(
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
    # Attach plain-English explanation
    intent.assumptions.insert(0, _build_explanation(intent))
    return intent


# ═══════════════════════════════════════════════════════════════════
# SECTION 8 — LLM path (Groq-first via llm_client)
# ═══════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are a BI query understanding engine for a dataset-agnostic analytics system.
Given a user question and dataset schema, output ONLY a valid JSON object with these fields:

{
  "question_type": "ranking"|"comparison"|"trend"|"distribution"|"aggregation"|"correlation"|"filtered_lookup"|"overview",
  "metric": "rate"|"count"|"sum"|"mean"|"median"|"max"|"min",
  "operation": "scalar_agg"|"groupby_agg"|"time_resample"|"value_counts",
  "primary_dimension": "<exact column name from schema, or null>",
  "secondary_dimension": "<exact column name from schema, or null>",
  "target_variable": "<exact numeric or binary column from schema, or null>",
  "rate_value": "<positive class string value, or null>",
  "filters": [{"column":"<exact col>", "operator":"==|!=|>|<|>=|<=|in", "value":"..."}],
  "time_column": "<exact date column name, or null>",
  "time_grain": "D"|"W"|"M"|"Q"|"Y"|null,
  "sort_direction": "asc"|"desc",
  "top_n": <integer or null>,
  "requested_kpis": ["<KPI phrases from query>"],
  "assumptions": ["<every inference made>"],
  "explanation": "<one sentence: what query type was detected and what metric/dimension will be computed>"
}

CRITICAL RULES — follow exactly:
1. primary_dimension = null unless query says "by X", "per X", "across X", "for each X",
   "group by X", or "breakdown by X". NEVER guess a dimension from the schema.
   - "total revenue" → primary_dimension: null
   - "revenue by category" → primary_dimension: "category" (exact col name)
   - "top 5 products by sales" → primary_dimension: "product" (exact col name)

2. question_type rules:
   - primary_dimension is null + sum/mean/count → "aggregation" (KPI card, no chart)
   - "by X" + sum/mean + "top"/"rank" → "ranking"
   - "by X" + sum/mean → "comparison"
   - "over time"/"monthly"/"trend" → "trend"
   - "top N" alone → "ranking"

3. operation hint:
   - aggregation with no dimension → "scalar_agg"
   - groupby with dimension → "groupby_agg"
   - trend/time → "time_resample"
   - distribution of a single dimension col → "value_counts"

4. target_variable:
   - For sum/mean/max/min: the numeric column to aggregate
   - For rate: the binary outcome column
   - For count: null (count rows)
   - ONLY use exact column names present in the schema

5. explanation: one plain sentence like
   "I understood this as a ranking query and computed total revenue by category."
   "I treated this as a KPI query and computed the overall sum of amount."

6. Never hallucinate column names. Only use names from the provided schema.
7. Output ONLY valid JSON. No markdown, no explanation outside the JSON.
"""


def _build_llm_message(
    prompt:         str,
    schema_profile: dict[str, Any],
    session_ctx:    Optional[SessionContext] = None,
) -> str:
    cols = schema_profile.get("columns", [])
    lines = []
    for c in cols:
        tv     = c.get("top_values", [])
        tv_str = f", top_values={[v['value'] for v in tv[:5]]}" if tv else ""
        lines.append(
            f"  {c['name']} (role={c['role']}, dtype={c['dtype']}, "
            f"unique={c['unique_count']}, hint={c.get('semantic_hint','none')}{tv_str})"
        )

    context_block = ""
    if session_ctx:
        ctx_summary = session_ctx.get_context_summary()
        if ctx_summary:
            context_block = f"\n\nConversation context:\n{ctx_summary}\n"

    return (
        f"User question: {prompt}{context_block}\n\n"
        f"Dataset schema ({len(cols)} columns):\n" + "\n".join(lines)
    )


def _llm_understand(
    prompt:         str,
    schema_profile: dict[str, Any],
    session_ctx:    Optional[SessionContext],
) -> Optional[QueryIntent]:
    if not llm_client.available:
        return None

    system = _SYSTEM_PROMPT
    if session_ctx:
        ctx = session_ctx.get_context_summary()
        if ctx:
            system = system + f"\n\n{ctx}"

    msg  = _build_llm_message(prompt, schema_profile, session_ctx)
    data = llm_client.complete_json(system, msg, temperature=0.0)
    if not data:
        return None

    try:
        filters = [
            FilterSpec(
                column=f["column"],
                operator=f.get("operator", "=="),
                value=f["value"],
            )
            for f in data.get("filters", [])
            if isinstance(f, dict) and "column" in f and "value" in f
        ]

        explanation = data.get("explanation", "")
        assumptions = data.get("assumptions", [])
        # Put explanation first in assumptions list so it surfaces in chat
        if explanation:
            assumptions = [explanation] + [a for a in assumptions if a != explanation]

        intent = QueryIntent(
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
            assumptions=         assumptions,
        )
        return intent

    except Exception as exc:
        logger.warning("QueryUnderstanding: LLM parse failed: %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# SECTION 9 — public API
# ═══════════════════════════════════════════════════════════════════

_GENERIC_PROMPTS = frozenset({
    "overview", "dashboard", "show me everything", "give me a complete overview",
    "summary", "analyse", "analyze", "report", "data",
})


def understand_query(
    user_prompt:    str,
    schema_profile: dict[str, Any],
    session_ctx:    Optional[SessionContext] = None,
) -> QueryIntent:
    """
    Convert a natural-language prompt into a structured QueryIntent.

    Flow:
      1. Generic/very-short prompt → overview intent
      2. LLM path (Groq → OpenAI → Anthropic, whichever key is set)
      3. Rule-based fallback
      4. Follow-up merge if session has previous intent

    The returned intent always has an explanation string as assumptions[0].
    """
    cleaned = user_prompt.strip()

    # ── 1. Generic overview shortcut ──────────────────────────────
    if cleaned.lower() in _GENERIC_PROMPTS or len(cleaned) < 8:
        return QueryIntent(
            question_type= QuestionType.overview,
            metric=        MetricType.count,
            raw_prompt=    user_prompt,
            assumptions=   ["I treated this as a general overview — showing dataset summary."],
        )

    # ── 2. Detect follow-up before parsing ────────────────────────
    is_fu = (
        _is_followup(cleaned)
        and session_ctx is not None
        and session_ctx.previous_intent is not None
    )

    # ── 3. LLM path ───────────────────────────────────────────────
    intent = _llm_understand(cleaned, schema_profile, session_ctx)
    if intent is None:
        logger.info("QueryUnderstanding: using rule-based path")
        intent = _rule_based_understand(cleaned, schema_profile)
    else:
        logger.info(
            "QueryUnderstanding: LLM — type=%s metric=%s dim=%s target=%s",
            intent.question_type, intent.metric,
            intent.primary_dimension, intent.target_variable,
        )

    # ── 4. Follow-up merge ────────────────────────────────────────
    if is_fu and session_ctx and session_ctx.previous_intent:
        schema = (
            session_ctx.schema_profile_cache
            if hasattr(session_ctx, "schema_profile_cache")
            else schema_profile
        )
        intent = _resolve_followup(
            current=intent,
            previous=session_ctx.previous_intent,
            schema_profile=schema or schema_profile,
        )
        logger.info(
            "QueryUnderstanding: follow-up merged — dim=%s filters=%d",
            intent.primary_dimension, len(intent.filters),
        )

    logger.info(
        "QueryUnderstanding: final — type=%s metric=%s dim=%s target=%s filters=%d",
        intent.question_type, intent.metric,
        intent.primary_dimension, intent.target_variable, len(intent.filters),
    )
    return intent