"""
app/services/analysis_planning_agent.py
══════════════════════════════════════════════════════════════════════
Agent 2: Analysis Planner

Converts a QueryIntent → AnalysisPlan.

Key improvements:
  - Multi-groupby support (secondary_dimension)
  - formula_spec: human-readable formula string in response
  - refinement_hint: accepts a correction signal from ReflectionAgent
  - LLM path uses the shared llm_client (not a copy-pasted duplicate)
  - Rule-based path covers all QuestionType variants
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.llm_client import llm_client
from app.core.models import (
    AnalysisPlan, InferenceSource, MetricType, PlanOperation,
    QueryIntent, QuestionType,
)
from app.services.semantic_classifier import find_best_metric

import logging
logger = logging.getLogger(__name__)


# ── LLM prompt ────────────────────────────────────────────────────

_PLANNER_SYSTEM = """You are an analysis planning engine for a BI system.
Given a QueryIntent and schema, produce a concrete AnalysisPlan as JSON.

Output ONLY valid JSON:
{
  "operations": [
    {"step":1, "op":"filter|groupby_agg|value_counts|sort|top_n|time_resample", "args":{...}}
  ],
  "result_columns": ["col1","col2"],
  "x_field": "...",
  "y_field": "...",
  "metric_label": "...",
  "result_label": "...",
  "formula_spec": "human-readable formula",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence"
}

Operation args:
  filter:        {"column":"...","operator":"==|!=|>|<|>=|<=","value":"..."}
  groupby_agg:   {"group_by":["col1","col2"],"target":"col","agg_fn":"rate|count|mean|sum|median|max|min","rate_value":"yes"}
  value_counts:  {"column":"col","normalize":false}
  sort:          {"by":"value","ascending":false}
  top_n:         {"n":10}
  time_resample: {"date_col":"col","freq":"M|Q|Y|D|W","target":"col","agg_fn":"count|sum|mean"}

RULES:
- rate = mean(target == rate_value) grouped by dimension
- Always add sort step for ranking/comparison questions
- top_n only if explicitly requested or > 15 result rows expected
- formula_spec must be human-readable: e.g. "Subscription Rate (y='yes') by Job Category, sorted descending"
- Output ONLY JSON. No markdown.
"""


def _planner_user_message(intent: QueryIntent, schema_profile: dict[str, Any]) -> str:
    import json as _json
    intent_dict = intent.dict()
    cols = schema_profile.get("columns", [])
    col_summary = "\n".join(
        f"  {c['name']} (role={c['role']}, hint={c.get('semantic_hint','none')}, "
        f"unique={c['unique_count']}"
        + (f", top={[v['value'] for v in c.get('top_values',[])[:4]]}" if c.get('top_values') else "")
        + ")"
        for c in cols
    )
    return f"QueryIntent:\n{_json.dumps(intent_dict, indent=2)}\n\nSchema:\n{col_summary}"


# ── rule-based planner ────────────────────────────────────────────

def _metric_label(metric: str, target: Optional[str]) -> str:
    labels = {
        "rate":   f"{target or 'Outcome'} Rate",
        "count":  "Count",
        "sum":    f"Total {target or 'Value'}",
        "mean":   f"Average {target or 'Value'}",
        "median": f"Median {target or 'Value'}",
        "max":    f"Max {target or 'Value'}",
        "min":    f"Min {target or 'Value'}",
    }
    return labels.get(metric, metric.title())


def _formula_spec(intent: QueryIntent) -> str:
    """Build a human-readable formula string."""
    metric    = intent.metric
    target    = intent.target_variable or "value"
    dim       = intent.primary_dimension or "category"
    second    = intent.secondary_dimension
    rate_val  = intent.rate_value or "yes"
    direction = "descending" if intent.sort_direction == "desc" else "ascending"

    if metric == MetricType.rate:
        base = f"Rate({target} = '{rate_val}')"
    elif metric == MetricType.count:
        base = f"Count of rows"
    elif metric in (MetricType.mean, MetricType.median):
        base = f"{metric.title()}({target})"
    else:
        base = f"{metric.title()}({target})"

    grouping = f"grouped by {dim}"
    if second:
        grouping += f" and {second}"

    if intent.question_type == QuestionType.trend:
        return f"{base} over time ({intent.time_column})"

    sort_str = ""
    if intent.question_type in (QuestionType.ranking, QuestionType.comparison):
        sort_str = f", sorted {direction}"
    if intent.top_n:
        sort_str += f", top {intent.top_n}"

    return f"{base} {grouping}{sort_str}"


def _rule_based_plan(
    intent:        QueryIntent,
    schema_profile: dict[str, Any],
    refinement_hint: Optional[dict[str, Any]] = None,
) -> AnalysisPlan:
    ops:   list[PlanOperation] = []
    step   = 1
    cols   = schema_profile.get("columns", [])

    metric        = str(intent.metric)
    primary_dim   = intent.primary_dimension
    second_dim    = intent.secondary_dimension
    target_var    = intent.target_variable
    time_col      = intent.time_column
    time_grain    = intent.time_grain or "M"
    sort_dir      = intent.sort_direction == "asc"  # ascending=True means asc
    top_n         = intent.top_n

    # apply refinement hint
    if refinement_hint:
        if "change_metric" in refinement_hint:
            metric = refinement_hint["change_metric"]
            logger.info("PlanBuilder: refinement applied — metric changed to %s", metric)
        if "change_rate_value" in refinement_hint:
            intent = intent.copy(update={"rate_value": refinement_hint["change_rate_value"]})

    # ── filter operations ─────────────────────────────────────────
    for filt in intent.filters:
        ops.append(PlanOperation(
            step=step, op="filter",
            args={"column": filt.column, "operator": filt.operator, "value": filt.value},
        ))
        step += 1

    # ── main aggregation ──────────────────────────────────────────
    group_by = [g for g in [primary_dim, second_dim] if g]

    if intent.question_type == QuestionType.trend and time_col:
        ops.append(PlanOperation(
            step=step, op="time_resample",
            args={
                "date_col": time_col,
                "freq":     time_grain,
                "target":   target_var or primary_dim,
                "agg_fn":   metric if metric != "rate" else "count",
            },
        ))
        step += 1
        x_field = time_col
        y_field = "value"

    elif group_by:
        agg_args: dict[str, Any] = {
            "group_by": group_by,
            "target":   target_var or (
                find_best_metric(cols) if metric != "count" else group_by[0]
            ),
            "agg_fn":   metric,
        }
        if metric == "rate":
            agg_args["rate_value"] = intent.rate_value or "yes"

        ops.append(PlanOperation(step=step, op="groupby_agg", args=agg_args))
        step += 1
        x_field = primary_dim or group_by[0]
        y_field = "value"

    elif intent.question_type == QuestionType.distribution and primary_dim:
        ops.append(PlanOperation(
            step=step, op="value_counts",
            args={"column": primary_dim, "normalize": False},
        ))
        step += 1
        x_field = primary_dim
        y_field = "value"

    else:
        # absolute fallback: value_counts on best dimension
        from app.services.semantic_classifier import find_best_dimension
        best = find_best_dimension(cols) or (cols[0]["name"] if cols else "unknown")
        ops.append(PlanOperation(
            step=step, op="value_counts",
            args={"column": best, "normalize": False},
        ))
        step += 1
        x_field = best
        y_field = "value"

    # ── sort ──────────────────────────────────────────────────────
    if intent.question_type in (
        QuestionType.ranking, QuestionType.comparison, QuestionType.aggregation
    ):
        ops.append(PlanOperation(
            step=step, op="sort",
            args={"by": "value", "ascending": sort_dir},
        ))
        step += 1

    # ── top_n ─────────────────────────────────────────────────────
    if top_n:
        ops.append(PlanOperation(step=step, op="top_n", args={"n": top_n}))
        step += 1
    elif intent.question_type == QuestionType.ranking:
        # default top 15 for ranking
        ops.append(PlanOperation(step=step, op="top_n", args={"n": 15}))
        step += 1

    ml = _metric_label(metric, target_var)
    rl = f"{ml} by {primary_dim.title()}" if primary_dim else ml

    return AnalysisPlan(
        operations=     ops,
        result_columns= [x_field, y_field],
        x_field=        x_field,
        y_field=        y_field,
        metric_label=   ml,
        result_label=   rl,
        formula_spec=   _formula_spec(intent),
        confidence=     0.82,
        reasoning=      (
            f"Rule-based plan: {intent.question_type}, metric={metric}, "
            f"dim={primary_dim}, target={target_var}"
        ),
    )


# ── LLM path ─────────────────────────────────────────────────────

def _llm_plan(
    intent: QueryIntent, schema_profile: dict[str, Any]
) -> Optional[AnalysisPlan]:
    if not llm_client.available:
        return None

    msg  = _planner_user_message(intent, schema_profile)
    data = llm_client.complete_json(_PLANNER_SYSTEM, msg, temperature=0.0)
    if not data or not data.get("operations"):
        return None

    try:
        ops = [
            PlanOperation(step=o["step"], op=o["op"], args=o.get("args", {}))
            for o in data["operations"]
        ]
        return AnalysisPlan(
            operations=     ops,
            result_columns= data.get("result_columns", []),
            x_field=        data.get("x_field", ""),
            y_field=        data.get("y_field", "value"),
            metric_label=   data.get("metric_label", "Value"),
            result_label=   data.get("result_label", "Analysis Result"),
            formula_spec=   data.get("formula_spec", ""),
            confidence=     float(data.get("confidence", 0.85)),
            reasoning=      data.get("reasoning", ""),
        )
    except Exception as exc:
        logger.warning("PlanBuilder: LLM response parse failed: %s", exc)
        return None


# ── public API ────────────────────────────────────────────────────

def build_analysis_plan(
    intent:          QueryIntent,
    schema_profile:  dict[str, Any],
    refinement_hint: Optional[dict[str, Any]] = None,
) -> AnalysisPlan:
    """
    Convert QueryIntent → AnalysisPlan.
    refinement_hint: optional correction from ReflectionAgent retry loop.
    """
    if refinement_hint is None and llm_client.available:
        plan = _llm_plan(intent, schema_profile)
        if plan:
            logger.info("PlanBuilder: LLM path, %d operations", len(plan.operations))
            return plan
        logger.info("PlanBuilder: LLM failed, using rule-based plan")

    return _rule_based_plan(intent, schema_profile, refinement_hint)