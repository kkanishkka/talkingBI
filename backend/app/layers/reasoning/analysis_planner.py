"""
app/layers/reasoning/analysis_planner.py
══════════════════════════════════════════════════════════════════════
Analysis Planner — v3

Bugs fixed vs v2:
  ① KPI path added: when intent has no primary_dimension and
    question_type is aggregation, the plan produces a SINGLE-ROW
    scalar result (sum/mean/count of the target column) using the new
    "scalar_agg" operation, not value_counts or groupby_agg.

  ② Fallback else-branch no longer calls find_best_dimension() and
    value_counts blindly. If intent has no dimension and no clear
    distribution structure, returns scalar KPI.

  ③ LLM system prompt updated to reflect KPI path and scalar_agg op.

  ④ _rule_based_plan decision tree is now explicit and exhaustive:
     trend → time_resample
     dimension present → groupby_agg
     distribution with dimension → value_counts
     aggregation / KPI (no dim) → scalar_agg
     fallback → scalar_agg count

  ⑤ metric_label and result_label are cleaner for KPI responses.

Architecture preserved: LLM → rule-based fallback, same AnalysisPlan
output shape.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.llm_client import llm_client
from app.core.models import (
    AnalysisPlan, MetricType, PlanOperation,
    QueryIntent, QuestionType,
)
from app.layers.semantic.semantic_classifier import find_best_metric, find_best_dimension

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — label helpers
# ═══════════════════════════════════════════════════════════════════

def _metric_label(metric: str, target: Optional[str]) -> str:
    labels = {
        "rate":   f"{target or 'Outcome'} Rate",
        "count":  "Count",
        "sum":    f"Total {target.replace('_', ' ').title() if target else 'Value'}",
        "mean":   f"Average {target.replace('_', ' ').title() if target else 'Value'}",
        "median": f"Median {target.replace('_', ' ').title() if target else 'Value'}",
        "max":    f"Max {target.replace('_', ' ').title() if target else 'Value'}",
        "min":    f"Min {target.replace('_', ' ').title() if target else 'Value'}",
    }
    return labels.get(metric, metric.title())


def _formula_spec(intent: QueryIntent) -> str:
    metric    = str(intent.metric)
    target    = intent.target_variable or "value"
    dim       = intent.primary_dimension
    second    = intent.secondary_dimension
    rate_val  = intent.rate_value or "yes"
    direction = "descending" if intent.sort_direction == "desc" else "ascending"

    if metric == MetricType.rate:
        base = f"Rate({target} = '{rate_val}')"
    elif metric == MetricType.count:
        base = "Count of rows"
    else:
        base = f"{metric.title()}({target})"

    if intent.question_type == QuestionType.trend:
        return f"{base} over time ({intent.time_column})"

    if intent.question_type == QuestionType.aggregation and not dim:
        return f"{base} — overall KPI"

    grouping = f"grouped by {dim}" if dim else ""
    if second:
        grouping += f" and {second}"

    sort_str = ""
    if intent.question_type in (QuestionType.ranking, QuestionType.comparison):
        sort_str = f", sorted {direction}"
    if intent.top_n:
        sort_str += f", top {intent.top_n}"

    return f"{base} {grouping}{sort_str}".strip()


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — rule-based planner
# ═══════════════════════════════════════════════════════════════════

def _rule_based_plan(
    intent:          QueryIntent,
    schema_profile:  dict[str, Any],
    refinement_hint: Optional[dict[str, Any]] = None,
) -> AnalysisPlan:
    ops:   list[PlanOperation] = []
    step   = 1
    cols   = schema_profile.get("columns", [])

    metric      = str(intent.metric)
    primary_dim = intent.primary_dimension
    second_dim  = intent.secondary_dimension
    target_var  = intent.target_variable
    time_col    = intent.time_column
    time_grain  = intent.time_grain or "M"
    sort_asc    = intent.sort_direction == "asc"
    top_n       = intent.top_n

    # Apply refinement hint if provided
    if refinement_hint:
        if "change_metric" in refinement_hint:
            metric = refinement_hint["change_metric"]
            logger.info("PlanBuilder: refinement — metric → %s", metric)
        if "change_rate_value" in refinement_hint:
            intent = intent.copy(update={"rate_value": refinement_hint["change_rate_value"]})

    # ── Step 1: Apply filters ─────────────────────────────────────
    for filt in intent.filters:
        ops.append(PlanOperation(
            step=step, op="filter",
            args={"column": filt.column, "operator": filt.operator, "value": filt.value},
        ))
        step += 1

    group_by = [g for g in [primary_dim, second_dim] if g]

    # ── Branch A: Trend ───────────────────────────────────────────
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
        x_field, y_field = time_col, "value"

    # ── Branch B: Grouped analysis (has dimension) ─────────────────
    elif group_by:
        # Resolve target column for groupby_agg
        agg_target = target_var
        if agg_target is None and metric != "count":
            agg_target = find_best_metric(cols) or group_by[0]

        agg_args: dict[str, Any] = {
            "group_by": group_by,
            "target":   agg_target or group_by[0],
            "agg_fn":   metric,
        }
        if metric == "rate":
            agg_args["rate_value"] = intent.rate_value or "yes"

        ops.append(PlanOperation(step=step, op="groupby_agg", args=agg_args))
        step += 1

        # Sort for ranking/comparison
        if intent.question_type in (QuestionType.ranking, QuestionType.comparison,
                                     QuestionType.aggregation):
            ops.append(PlanOperation(
                step=step, op="sort",
                args={"by": "value", "ascending": sort_asc},
            ))
            step += 1

        # Top-N limit
        effective_top_n = top_n
        if effective_top_n is None and intent.question_type == QuestionType.ranking:
            effective_top_n = 15
        if effective_top_n:
            ops.append(PlanOperation(step=step, op="top_n", args={"n": effective_top_n}))
            step += 1

        x_field = primary_dim or group_by[0]
        y_field = "value"

    # ── Branch C: Distribution (no explicit dim but dist intent) ──
    elif intent.question_type == QuestionType.distribution:
        # Pick the best dimension for distribution — ONLY for distribution intent
        best_dim = find_best_dimension(cols)
        if best_dim:
            ops.append(PlanOperation(
                step=step, op="value_counts",
                args={"column": best_dim, "normalize": False},
            ))
            step += 1
            ops.append(PlanOperation(
                step=step, op="sort",
                args={"by": "value", "ascending": False},
            ))
            step += 1
            ops.append(PlanOperation(step=step, op="top_n", args={"n": 15}))
            step += 1
            x_field, y_field = best_dim, "value"
        else:
            # No dimension available — fall through to scalar
            x_field, y_field = _build_scalar_agg(ops, step, metric, target_var, cols)

    # ── Branch D: KPI / Aggregation (no dimension) — FIXED ────────
    else:
        # This is the KPI path. No grouping. Produce a single scalar result.
        x_field, y_field = _build_scalar_agg(ops, step, metric, target_var, cols)

    # ── Labels ────────────────────────────────────────────────────
    ml = _metric_label(metric, target_var)
    if primary_dim:
        rl = f"{ml} by {primary_dim.replace('_', ' ').title()}"
    else:
        rl = ml  # KPI: just "Total Revenue" etc.

    return AnalysisPlan(
        operations=     ops,
        result_columns= [x_field, y_field],
        x_field=        x_field,
        y_field=        y_field,
        metric_label=   ml,
        result_label=   rl,
        formula_spec=   _formula_spec(intent),
        confidence=     0.82,
        reasoning=(
            f"Rule-based plan: {intent.question_type}, metric={metric}, "
            f"dim={primary_dim}, target={target_var}"
        ),
    )


def _build_scalar_agg(
    ops:       list[PlanOperation],
    step:      int,
    metric:    str,
    target_var: Optional[str],
    cols:      list[dict[str, Any]],
) -> tuple[str, str]:
    """
    Append a scalar_agg operation and return (x_field, y_field).
    scalar_agg computes a single aggregate value over the whole column.
    Falls back to count-rows if no numeric column available.
    """
    # Resolve target column for the scalar
    agg_target = target_var
    if agg_target is None and metric != "count":
        agg_target = find_best_metric(cols)

    if agg_target and metric != "count":
        ops.append(PlanOperation(
            step=step, op="scalar_agg",
            args={"target": agg_target, "agg_fn": metric},
        ))
        return "metric", "value"
    else:
        # count rows
        ops.append(PlanOperation(
            step=step, op="scalar_agg",
            args={"target": None, "agg_fn": "count"},
        ))
        return "metric", "value"


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — LLM path
# ═══════════════════════════════════════════════════════════════════

_PLANNER_SYSTEM = """You are an analysis planning engine for a dataset-agnostic BI system.
Given a QueryIntent and schema, produce a concrete AnalysisPlan as JSON.

Output ONLY valid JSON:
{
  "operations": [
    {"step":1, "op":"filter|groupby_agg|scalar_agg|value_counts|sort|top_n|time_resample", "args":{...}}
  ],
  "result_columns": ["col1","col2"],
  "x_field": "...",
  "y_field": "value",
  "metric_label": "...",
  "result_label": "...",
  "formula_spec": "human-readable formula",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence"
}

Operation args:
  filter:       {"column":"...","operator":"==|!=|>|<|>=|<=","value":"..."}
  groupby_agg:  {"group_by":["col1"],"target":"col","agg_fn":"rate|count|mean|sum|median|max|min","rate_value":"yes"}
  scalar_agg:   {"target":"col_or_null","agg_fn":"count|sum|mean|median|max|min"}
  value_counts: {"column":"col","normalize":false}
  sort:         {"by":"value","ascending":false}
  top_n:        {"n":10}
  time_resample:{"date_col":"col","freq":"M|Q|Y|D|W","target":"col","agg_fn":"count|sum|mean"}

CRITICAL RULES:
- If intent.primary_dimension is null → use scalar_agg (KPI path), NOT groupby_agg or value_counts
- scalar_agg produces ONE ROW: {"metric": "<label>", "value": <number>}
- x_field = "metric", y_field = "value" for scalar_agg output
- Always add sort for ranking/comparison
- formula_spec must be human-readable
- Output ONLY JSON. No markdown.
"""


def _planner_user_message(intent: QueryIntent, schema_profile: dict[str, Any]) -> str:
    import json as _json
    cols = schema_profile.get("columns", [])
    col_summary = "\n".join(
        f"  {c['name']} (role={c['role']}, hint={c.get('semantic_hint','none')}, "
        f"unique={c['unique_count']}"
        + (f", top={[v['value'] for v in c.get('top_values',[])[:4]]}" if c.get('top_values') else "")
        + ")"
        for c in cols
    )
    return (
        f"QueryIntent:\n{_json.dumps(intent.dict(), indent=2)}\n\n"
        f"Schema:\n{col_summary}"
    )


def _llm_plan(intent: QueryIntent, schema_profile: dict[str, Any]) -> Optional[AnalysisPlan]:
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
            x_field=        data.get("x_field", "metric"),
            y_field=        data.get("y_field", "value"),
            metric_label=   data.get("metric_label", "Value"),
            result_label=   data.get("result_label", "Analysis Result"),
            formula_spec=   data.get("formula_spec", ""),
            confidence=     float(data.get("confidence", 0.85)),
            reasoning=      data.get("reasoning", ""),
        )
    except Exception as exc:
        logger.warning("PlanBuilder: LLM parse failed: %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# SECTION 4 — public API
# ═══════════════════════════════════════════════════════════════════

def build_analysis_plan(
    intent:          QueryIntent,
    schema_profile:  dict[str, Any],
    refinement_hint: Optional[dict[str, Any]] = None,
) -> AnalysisPlan:
    if refinement_hint is None and llm_client.available:
        plan = _llm_plan(intent, schema_profile)
        if plan:
            logger.info("PlanBuilder: LLM path, %d operations", len(plan.operations))
            return plan
        logger.info("PlanBuilder: LLM failed, using rule-based plan")
    return _rule_based_plan(intent, schema_profile, refinement_hint)