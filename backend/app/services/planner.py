"""
app/services/planner.py
══════════════════════════════════════════════════════════════════════
Dashboard Planner — schema-agnostic, multi-chart.

v2 changes (schema-agnostic refactor):
  ① Removed ALL hardcoded column/domain patterns:
       "sales|profit|revenue|amount|quantity|discount|cost|..." → GONE
       "and profit|and sales|and revenue" → GONE
     Replaced by schema-driven detection using column roles and
     semantic hints from the profiler.

  ② _is_dashboard_query() now detects dashboard intent purely from
     query language signals (verbs/connectives) + intent type,
     NOT from column-name mentions.

  ③ _extract_mentioned_metrics() / _extract_mentioned_dimensions()
     match query tokens against ACTUAL column names from the live
     schema — no hard-coded name lists.

  ④ Minimum guarantee enforced: ≥2 charts + ≥1 KPI for any
     dashboard query, using whatever columns the schema provides.

  ⑤ LLM planner prompt made explicitly schema-driven: instructs
     the model to use only names from the provided schema.

Works identically for:
  - ecommerce (sales, category, sub_category)
  - healthcare (diagnosis, los, department)
  - finance (amount, account_type, region)
  - any other schema
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.llm_client import llm_client
from app.core.models import MetricType, QueryIntent, QuestionType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Data classes (unchanged)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class KPIDefinition:
    """A single KPI card: one scalar metric with no grouping."""
    label:   str
    metric:  str          # sum | count | mean | max | min
    target:  Optional[str]  # column to aggregate, None → count rows
    formula: str          # human-readable: "SUM(sales)"
    value:   Optional[float] = None


@dataclass
class SubPlan:
    """One chart plan: aggregation of a metric over one dimension."""
    id:             str
    question_type:  str   # ranking | comparison | trend | distribution
    metric:         str
    target:         Optional[str]
    dimension:      Optional[str]
    time_column:    Optional[str]
    time_grain:     Optional[str]
    filters:        list[dict]
    sort_direction: str
    top_n:          Optional[int]
    rate_value:     Optional[str]
    label:          str
    formula:        str
    chart_hint:     str


@dataclass
class DashboardPlan:
    """Full multi-chart plan for one user query."""
    query_summary:   str
    kpi_definitions: list[KPIDefinition] = field(default_factory=list)
    sub_plans:       list[SubPlan]       = field(default_factory=list)
    assumptions:     list[str]           = field(default_factory=list)
    is_dashboard:    bool                = False

    @property
    def total_panels(self) -> int:
        return len(self.kpi_definitions) + len(self.sub_plans)


# ═══════════════════════════════════════════════════════════════════
# Dashboard intent detection — query language only, no domain words
# ═══════════════════════════════════════════════════════════════════

# These are LANGUAGE signals, not domain-specific column names.
_DASHBOARD_VERBS = re.compile(
    r"\b(analyz|analyse|analyze|compare|dashboard|overview|report|"
    r"full\s+analysis|break\s*down|summarize|summarise|"
    r"explore|investigate|assess|evaluate)\b",
    re.I,
)

# Connectives that imply multi-metric intent: "X and Y", "X vs Y"
_MULTI_CONCEPT = re.compile(
    r"\b(and|vs\.?|versus|along with|as well as|together with|both)\b",
    re.I,
)


def _is_dashboard_query(intent: QueryIntent, schema_profile: dict) -> bool:
    """
    Return True when the user clearly wants a multi-chart dashboard.
    Decision is based on:
      1. Query language signals (verbs, connectives)
      2. QuestionType from understanding layer
      3. Whether the query mentions multiple schema columns

    Never uses hardcoded domain words like 'sales', 'profit', etc.
    """
    prompt = intent.raw_prompt

    # Verb signals
    if _DASHBOARD_VERBS.search(prompt):
        return True

    # Intent type signals
    if intent.question_type in (QuestionType.overview, QuestionType.comparison):
        return True

    # Secondary dimension set → multi-dimensional request
    if intent.secondary_dimension:
        return True

    # "X and Y" where X and Y are both actual column names in the schema
    if _MULTI_CONCEPT.search(prompt):
        col_names = [c["name"].lower() for c in schema_profile.get("columns", [])]
        tokens = re.findall(r"[a-z0-9_]+", prompt.lower())
        # count how many schema column tokens appear in query
        col_mentions = sum(1 for t in tokens if t in col_names)
        if col_mentions >= 2:
            return True

    return False


# ═══════════════════════════════════════════════════════════════════
# Schema-driven metric / dimension extraction
# ═══════════════════════════════════════════════════════════════════

def _tokenise(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _col_tokens(name: str) -> set[str]:
    """Split snake_case / camelCase column name into token set."""
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return set(re.findall(r"[a-z0-9]+", parts.lower()))


def _query_mentions(query_tokens: list[str], col_name: str) -> bool:
    """True if any token in query overlaps with the column's token set."""
    return bool(_col_tokens(col_name) & set(query_tokens))


def _extract_mentioned_metrics(
    prompt:  str,
    columns: list[dict],
) -> list[str]:
    """
    Return metric column names that are explicitly mentioned in the prompt,
    OR all high-value metric columns if none are mentioned.

    Uses token matching against actual column names — no hardcoded lists.
    """
    metric_cols = [c for c in columns if c["role"] == "metric"
                   and c.get("semantic_hint") not in ("likely_id",)]
    if not metric_cols:
        return []

    query_tokens = _tokenise(prompt)
    mentioned = [c["name"] for c in metric_cols if _query_mentions(query_tokens, c["name"])]

    if not mentioned:
        # Fall back: pick top metrics by semantic priority
        # currency > count_field > score > none (all are good metrics)
        priority = ["currency", "count_field", "score", "none", "percentage"]
        seen = set()
        for hint in priority:
            for col in metric_cols:
                if col.get("semantic_hint") == hint and col["name"] not in seen:
                    mentioned.append(col["name"])
                    seen.add(col["name"])
                    if len(mentioned) >= 2:
                        break
            if len(mentioned) >= 2:
                break
        # still nothing → just take first 2
        if not mentioned:
            mentioned = [c["name"] for c in metric_cols[:2]]

    return mentioned


def _extract_mentioned_dimensions(
    prompt:   str,
    columns:  list[dict],
    max_dims: int = 3,
) -> list[str]:
    """
    Return dimension columns explicitly or implicitly wanted.
    Excludes likely_id and high_cardinality columns.
    Uses token matching — no hardcoded domain lists.
    """
    excluded_hints = {"likely_id", "high_cardinality"}
    dim_cols = [
        c for c in columns
        if c["role"] == "dimension"
        and c.get("semantic_hint") not in excluded_hints
        and c["unique_count"] > 1
    ]
    if not dim_cols:
        return []

    query_tokens = _tokenise(prompt)
    mentioned = [c["name"] for c in dim_cols if _query_mentions(query_tokens, c["name"])]

    if not mentioned:
        # pick best analytical dims: category_key first, then by cardinality 2–30
        category_key = [c for c in dim_cols if c.get("semantic_hint") == "category_key"]
        other_low    = [c for c in dim_cols
                        if 2 <= c["unique_count"] <= 30
                        and c.get("semantic_hint") != "category_key"]
        candidates   = category_key + other_low
        candidates.sort(key=lambda c: c["unique_count"])
        mentioned    = [c["name"] for c in candidates[:max_dims]]

    return mentioned[:max_dims]


# ═══════════════════════════════════════════════════════════════════
# Shared label / hint helpers
# ═══════════════════════════════════════════════════════════════════

def _metric_label(metric: str, target: Optional[str]) -> str:
    pretty = (target or "value").replace("_", " ").title()
    return {
        "sum":    f"Total {pretty}",
        "mean":   f"Average {pretty}",
        "count":  "Count",
        "max":    f"Max {pretty}",
        "min":    f"Min {pretty}",
        "median": f"Median {pretty}",
        "rate":   f"{pretty} Rate",
    }.get(metric, f"{metric.title()} {pretty}")


def _chart_hint(question_type: str, row_count_hint: int = 10) -> str:
    if question_type == "trend":
        return "line"
    if question_type in ("ranking", "comparison"):
        return "horizontal_bar" if row_count_hint > 7 else "bar"
    if question_type == "distribution":
        return "bar"
    return "bar"


def _build_kpi(metric: str, target: Optional[str]) -> KPIDefinition:
    label   = _metric_label(metric, target)
    formula = f"{metric.upper()}({target})" if target else "COUNT(*)"
    return KPIDefinition(label=label, metric=metric, target=target, formula=formula)


def _build_sub_plan(
    idx:           int,
    metric:        str,
    target:        Optional[str],
    dimension:     str,
    question_type: str,
    sort_dir:      str,
    top_n:         Optional[int],
    filters:       list[dict],
    rate_value:    Optional[str],
    time_column:   Optional[str],
    time_grain:    Optional[str],
) -> SubPlan:
    label   = _metric_label(metric, target)
    dim_pretty = dimension.replace("_", " ").title()
    qt = question_type if question_type != "aggregation" else "comparison"
    formula = (
        f"{metric.upper()}({target or '*'}) grouped by {dimension}, sorted {sort_dir}"
        + (f", top {top_n}" if top_n else "")
    )
    return SubPlan(
        id=             f"sub_{idx}",
        question_type=  qt,
        metric=         metric,
        target=         target,
        dimension=      dimension,
        time_column=    time_column,
        time_grain=     time_grain,
        filters=        filters,
        sort_direction= sort_dir,
        top_n=          top_n or 10,
        rate_value=     rate_value,
        label=          f"{label} by {dim_pretty}",
        formula=        formula,
        chart_hint=     _chart_hint(qt),
    )


# ═══════════════════════════════════════════════════════════════════
# LLM planner — schema-driven prompt
# ═══════════════════════════════════════════════════════════════════

_PLANNER_SYSTEM = """\
You are a BI dashboard planning engine.
Given a user query and schema, output a MULTI-CHART dashboard plan as JSON.

Output ONLY valid JSON:
{
  "is_dashboard": true|false,
  "query_summary": "one sentence describing what is being analysed",
  "kpis": [
    {"metric": "sum|count|mean|max|min", "target": "<exact column name or null>", "label": "..."}
  ],
  "charts": [
    {
      "metric": "sum|count|mean|rate",
      "target": "<exact metric column name or null>",
      "dimension": "<exact groupby column name>",
      "question_type": "ranking|comparison|distribution|trend",
      "sort_direction": "desc|asc",
      "top_n": 10,
      "chart_hint": "bar|horizontal_bar|line|pie",
      "label": "..."
    }
  ],
  "assumptions": ["..."]
}

CRITICAL RULES:
1. Use ONLY column names from the provided schema — never invent column names.
2. If the query mentions "analyze", "compare", "dashboard", or uses a connective
   like "and" between two schema columns: set is_dashboard=true, produce
   AT LEAST 2 kpis AND 3 charts.
3. For each metric column mentioned in the query, create one KPI card and
   one chart per available dimension.
4. dimension must be a groupable dimension column (role=dimension, low cardinality).
5. target for sum/mean must be a numeric metric column (role=metric).
6. If no specific metrics are mentioned, use all currency/count metric columns.
7. Output ONLY valid JSON. No markdown.
"""


def _llm_plan(intent: QueryIntent, schema_profile: dict) -> Optional[DashboardPlan]:
    if not llm_client.available:
        return None

    cols = schema_profile.get("columns", [])
    col_lines = "\n".join(
        f"  {c['name']} (role={c['role']}, hint={c.get('semantic_hint','none')}, "
        f"unique={c['unique_count']}"
        + (f", top={[v['value'] for v in c.get('top_values', [])[:4]]}"
           if c.get("top_values") else "")
        + ")"
        for c in cols
    )
    user_msg = (
        f"User query: {intent.raw_prompt}\n\n"
        f"Schema ({len(cols)} columns):\n{col_lines}"
    )

    data = llm_client.complete_json(_PLANNER_SYSTEM, user_msg, temperature=0.0)
    if not data:
        return None

    try:
        filters = [
            f.dict() if hasattr(f, "dict") else vars(f)
            for f in intent.filters
        ]

        kpis = []
        for k in data.get("kpis", []):
            # Validate target column exists in schema
            target = k.get("target")
            col_names = {c["name"] for c in cols}
            if target and target not in col_names:
                logger.warning("LLM planner: unknown column '%s' in KPI, skipping", target)
                continue
            kpis.append(KPIDefinition(
                label=   k.get("label", _metric_label(k["metric"], target)),
                metric=  k["metric"],
                target=  target,
                formula= f"{k['metric'].upper()}({target or '*'})",
            ))

        sub_plans = []
        for i, c in enumerate(data.get("charts", [])):
            target = c.get("target")
            dim    = c.get("dimension")
            # Validate both columns exist
            if target and target not in col_names:
                logger.warning("LLM planner: unknown target '%s', skipping chart", target)
                continue
            if dim and dim not in col_names:
                logger.warning("LLM planner: unknown dimension '%s', skipping chart", dim)
                continue
            sub_plans.append(SubPlan(
                id=             f"sub_{i}",
                question_type=  c.get("question_type", "comparison"),
                metric=         c["metric"],
                target=         target,
                dimension=      dim,
                time_column=    c.get("time_column"),
                time_grain=     c.get("time_grain"),
                filters=        filters,
                sort_direction= c.get("sort_direction", "desc"),
                top_n=          c.get("top_n", 10),
                rate_value=     intent.rate_value,
                label=          c.get("label", ""),
                formula=        c.get("label", ""),
                chart_hint=     c.get("chart_hint", "bar"),
            ))

        if not kpis and not sub_plans:
            return None

        return DashboardPlan(
            query_summary=   data.get("query_summary", intent.raw_prompt),
            kpi_definitions= kpis,
            sub_plans=       sub_plans,
            assumptions=     data.get("assumptions", []),
            is_dashboard=    data.get("is_dashboard", len(sub_plans) >= 3),
        )

    except Exception as exc:
        logger.warning("Planner LLM parse failed: %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# Rule-based planner — fully schema-driven
# ═══════════════════════════════════════════════════════════════════

def _rule_based_plan(intent: QueryIntent, schema_profile: dict) -> DashboardPlan:
    columns   = schema_profile.get("columns", [])
    is_dash   = _is_dashboard_query(intent, schema_profile)
    prompt    = intent.raw_prompt
    sort_dir  = intent.sort_direction or "desc"
    top_n     = intent.top_n or (10 if is_dash else None)
    filters   = [
        {"column": f.column, "operator": f.operator, "value": f.value}
        for f in intent.filters
    ]
    metric_str = str(intent.metric)
    rate_val   = intent.rate_value

    # ── Which metrics to show ──────────────────────────────────────
    if is_dash:
        metric_cols = _extract_mentioned_metrics(prompt, columns)
    else:
        primary = intent.target_variable
        if primary:
            metric_cols = [primary]
        else:
            metric_cols = _extract_mentioned_metrics(prompt, columns)[:1]

    # ── Which dimensions to group by ──────────────────────────────
    dims_requested = []
    if intent.primary_dimension:
        dims_requested.append(intent.primary_dimension)
    if intent.secondary_dimension and intent.secondary_dimension not in dims_requested:
        dims_requested.append(intent.secondary_dimension)

    if is_dash and not dims_requested:
        dims_requested = _extract_mentioned_dimensions(prompt, columns)

    # ── Build KPI definitions ─────────────────────────────────────
    kpis: list[KPIDefinition] = []
    seen_kpi: set = set()
    for mc in metric_cols:
        k = (metric_str, mc)
        if k in seen_kpi:
            continue
        seen_kpi.add(k)
        kpis.append(_build_kpi(metric_str, mc))

    if is_dash and len(kpis) < 2:
        fallback_metrics = _extract_mentioned_metrics(prompt, columns)
        for mc in fallback_metrics:
            if len(kpis) >= 2:
                break
            k = ("sum", mc)
            if k not in seen_kpi:
                seen_kpi.add(k)
                kpis.append(_build_kpi("sum", mc))

    if not kpis:
        kpis.append(_build_kpi("count", None))

    # ── Build chart sub-plans ─────────────────────────────────────
    sub_plans: list[SubPlan] = []
    idx = 0

    # Trend charts if time column present
    if intent.time_column:
        for mc in metric_cols[:1]:
            sub_plans.append(_build_sub_plan(
                idx=idx, metric=metric_str, target=mc,
                dimension=intent.time_column,
                question_type="trend",
                sort_dir="asc", top_n=None,
                filters=filters, rate_value=rate_val,
                time_column=intent.time_column,
                time_grain=intent.time_grain or "M",
            ))
            idx += 1

    # Groupby charts: metric × dimension matrix
    qt = str(intent.question_type)
    if qt in ("aggregation", "overview"):
        qt = "comparison"

    metrics_to_chart = metric_cols if is_dash else metric_cols[:1]
    dims_to_use      = dims_requested if dims_requested else []

    for dim in dims_to_use:
        for mc in metrics_to_chart:
            sub_plans.append(_build_sub_plan(
                idx=idx, metric=metric_str, target=mc,
                dimension=dim, question_type=qt,
                sort_dir=sort_dir, top_n=top_n,
                filters=filters, rate_value=rate_val,
                time_column=None, time_grain=None,
            ))
            idx += 1

    # ── Minimum guarantee for dashboard queries ───────────────────
    # If we still don't have 3 charts, pull best schema dims/metrics
    if is_dash and len(sub_plans) < 3:
        fallback_dims = _extract_mentioned_dimensions(prompt, columns, max_dims=3)
        fallback_metrics = _extract_mentioned_metrics(prompt, columns)

        for dim in fallback_dims:
            if len(sub_plans) >= 4:
                break
            if any(sp.dimension == dim for sp in sub_plans):
                continue
            mc = fallback_metrics[0] if fallback_metrics else None
            sub_plans.append(_build_sub_plan(
                idx=idx, metric=metric_str if mc else "count",
                target=mc, dimension=dim,
                question_type="distribution",
                sort_dir="desc", top_n=10,
                filters=filters, rate_value=None,
                time_column=None, time_grain=None,
            ))
            idx += 1

    assumptions = [
        f"Detected {len(metric_cols)} metric(s): {', '.join(metric_cols or ['count'])}",
        f"Detected {len(dims_requested)} dimension(s): {', '.join(dims_requested or ['none'])}",
        f"Dashboard mode: {is_dash}",
    ]
    assumptions += (intent.assumptions or [])

    return DashboardPlan(
        query_summary=   intent.raw_prompt,
        kpi_definitions= kpis,
        sub_plans=       sub_plans,
        assumptions=     assumptions,
        is_dashboard=    is_dash,
    )


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def plan_dashboard(intent: QueryIntent, schema_profile: dict) -> DashboardPlan:
    """
    Convert QueryIntent → DashboardPlan.
    Schema-agnostic: works for any table with any column names.
    LLM tried first; rule-based fallback if LLM unavailable or weak.
    """
    plan = _llm_plan(intent, schema_profile)
    if plan and plan.total_panels >= 2:
        logger.info(
            "Planner: LLM — %d KPIs, %d charts, is_dashboard=%s",
            len(plan.kpi_definitions), len(plan.sub_plans), plan.is_dashboard,
        )
        return plan

    if plan:
        logger.info("Planner: LLM produced <2 panels — augmenting with rule-based")
    else:
        logger.info("Planner: using rule-based path")

    return _rule_based_plan(intent, schema_profile)