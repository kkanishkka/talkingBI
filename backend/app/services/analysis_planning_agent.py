"""
app/services/analysis_planning_agent.py
════════════════════════════════════════════════════════════════════
Agent 2: Analysis Planner

Responsibility:
  Given a QueryIntent, produce a concrete AnalysisPlan — a list of
  ordered operations that the AnalysisExecutor can run deterministically
  against the pandas DataFrame.

  The planner knows HOW to compute each metric type:
    - rate:   boolean proportion of target_variable == rate_value
    - count:  value_counts or groupby size
    - mean:   groupby mean
    - sum:    groupby sum
    - median: groupby median
    - rank:   sort result by value

  The executor NEVER interprets intent — it only executes the plan.
  This separation is critical: it means the LLM can plan but cannot
  hallucinate data (only the deterministic executor touches the df).

Usage:
  from app.services.analysis_planning_agent import build_analysis_plan
  plan = build_analysis_plan(query_intent, schema_profile)
════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── LLM helpers (re-used from query_understanding_agent pattern) ──

def _llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


def _call_llm(system_prompt: str, user_message: str) -> str | None:
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
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception as exc:
            logger.warning("OpenAI call failed: %s", exc)
            return None

    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return resp.content[0].text
        except Exception as exc:
            logger.warning("Anthropic call failed: %s", exc)
            return None

    return None


# ── LLM prompt for planning ───────────────────────────────────────

_PLANNER_SYSTEM = """You are an analysis planning engine for a BI system.
Given a QueryIntent and schema, produce a concrete AnalysisPlan as JSON.

Output ONLY valid JSON with this schema:
{
  "operations": [
    {
      "step": 1,
      "op": "filter"|"groupby_agg"|"sort"|"top_n"|"value_counts"|"time_resample",
      "args": { ... op-specific arguments ... }
    }
  ],
  "result_columns": ["col1", "col2"],
  "x_field": "...",
  "y_field": "...",
  "metric_label": "...",
  "result_label": "...",
  "confidence": 0.0 to 1.0,
  "reasoning": "one sentence"
}

Operation arg schemas:
  filter:         {"column":"...","operator":"=="|"!="|">"|"<"|">="|"<=","value":"..."}
  groupby_agg:    {"group_by":["col"],"target":"col","agg_fn":"rate"|"count"|"mean"|"sum"|"median"|"max"|"min","rate_value":"yes"}
  value_counts:   {"column":"col","normalize":true|false}
  sort:           {"by":"col","ascending":false}
  top_n:          {"n":10}
  time_resample:  {"date_col":"col","freq":"M"|"Q"|"Y","target":"col","agg_fn":"count"|"sum"|"mean"}

Rules:
- For "rate" metric: use groupby_agg with agg_fn="rate" and rate_value=the positive value
- Always add a sort step for ranking questions
- Always add top_n for top-N questions
- result_columns must match what the executor will produce
- Output ONLY JSON. No markdown.
"""


def _build_planner_message(
    intent: dict[str, Any], schema_profile: dict[str, Any]
) -> str:
    cols = schema_profile.get("columns", [])
    col_info = "\n".join(
        f"  {c['name']} ({c['role']}, {c['dtype']}, "
        f"unique={c['unique_count']}"
        + (f", top_values={[v['value'] for v in c.get('top_values', [])[:4]]}"
           if c.get("top_values") else "")
        + ")"
        for c in cols
    )
    return (
        f"QueryIntent:\n{json.dumps(intent, indent=2)}\n\n"
        f"Schema columns:\n{col_info}"
    )


def _parse_llm_plan(raw: str) -> dict[str, Any] | None:
    try:
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse planner LLM response: %s", exc)
        return None


# ── rule-based planner ────────────────────────────────────────────

def _find_rate_value(
    target_col: str, schema_profile: dict[str, Any]
) -> str:
    """
    Determine what value counts as 'positive' for a rate calculation.
    Looks at top_values — picks 'yes', 'true', '1', or the less frequent value.
    """
    for col in schema_profile.get("columns", []):
        if col["name"] != target_col:
            continue
        top = col.get("top_values", [])
        if not top:
            return "yes"
        # common positive indicators
        for positive in ("yes", "true", "1", "success", "subscribed", "converted"):
            for tv in top:
                if str(tv["value"]).lower() == positive:
                    return tv["value"]
        # fallback: less frequent value is usually the positive event
        if len(top) >= 2:
            return min(top, key=lambda x: x["count"])["value"]
        return top[0]["value"]
    return "yes"


def _rule_based_plan(
    intent: dict[str, Any], schema_profile: dict[str, Any]
) -> dict[str, Any]:
    """Build an AnalysisPlan from QueryIntent using deterministic rules."""

    operations: list[dict[str, Any]] = []
    step = 1

    question_type  = intent.get("question_type", "distribution")
    metric         = intent.get("metric", "count")
    primary_dim    = intent.get("primary_dimension")
    target_var     = intent.get("target_variable")
    time_col       = intent.get("time_column")
    sort_direction = intent.get("sort_direction", "desc")
    top_n          = intent.get("top_n")
    filt           = intent.get("filter")

    # step: filter (optional)
    if filt:
        operations.append({
            "step": step,
            "op": "filter",
            "args": {
                "column":   filt["column"],
                "operator": filt.get("operator", "=="),
                "value":    filt["value"],
            },
        })
        step += 1

    # step: main aggregation
    if question_type == "trend" and time_col:
        freq = "M"
        if "year" in intent.get("raw_prompt", "").lower():
            freq = "Y"
        elif "quarter" in intent.get("raw_prompt", "").lower():
            freq = "Q"

        operations.append({
            "step": step,
            "op": "time_resample",
            "args": {
                "date_col": time_col,
                "freq":     freq,
                "target":   target_var or primary_dim,
                "agg_fn":   metric if metric != "rate" else "count",
            },
        })
        step += 1
        result_cols = [time_col, "value"]
        x_field     = time_col
        y_field     = "value"

    elif primary_dim and (target_var or metric in ("count",)):
        agg_fn = metric
        rate_value = None

        if metric == "rate" and target_var:
            rate_value = _find_rate_value(target_var, schema_profile)

        operations.append({
            "step": step,
            "op": "groupby_agg",
            "args": {
                "group_by":   [primary_dim],
                "target":     target_var or primary_dim,
                "agg_fn":     agg_fn,
                **({"rate_value": rate_value} if rate_value else {}),
            },
        })
        step += 1
        result_cols = [primary_dim, "value"]
        x_field     = primary_dim
        y_field     = "value"

    elif primary_dim:
        operations.append({
            "step": step,
            "op": "value_counts",
            "args": {"column": primary_dim, "normalize": False},
        })
        step += 1
        result_cols = [primary_dim, "value"]
        x_field     = primary_dim
        y_field     = "value"

    else:
        # last resort: profile the first dimension column
        dims = [c for c in schema_profile.get("columns", []) if c["role"] == "dimension"]
        col  = dims[0]["name"] if dims else "unknown"
        operations.append({
            "step": step,
            "op":  "value_counts",
            "args": {"column": col, "normalize": False},
        })
        step += 1
        result_cols = [col, "value"]
        x_field     = col
        y_field     = "value"

    # step: sort
    if question_type in ("ranking", "comparison", "aggregation"):
        operations.append({
            "step": step,
            "op":   "sort",
            "args": {"by": "value", "ascending": sort_direction == "asc"},
        })
        step += 1

    # step: top-N
    if top_n:
        operations.append({
            "step": step,
            "op":   "top_n",
            "args": {"n": top_n},
        })
        step += 1

    # metric label
    metric_labels = {
        "rate":   f"{target_var} Rate" if target_var else "Rate",
        "count":  "Count",
        "sum":    f"Total {target_var}" if target_var else "Total",
        "mean":   f"Average {target_var}" if target_var else "Average",
        "median": f"Median {target_var}" if target_var else "Median",
        "max":    f"Max {target_var}" if target_var else "Max",
        "min":    f"Min {target_var}" if target_var else "Min",
    }
    metric_label  = metric_labels.get(metric, metric.title())
    result_label  = (
        f"{metric_label} by {primary_dim.title()}"
        if primary_dim else metric_label
    )

    return {
        "operations":    operations,
        "result_columns": result_cols,
        "x_field":       x_field,
        "y_field":       y_field,
        "metric_label":  metric_label,
        "result_label":  result_label,
        "confidence":    0.80,
        "reasoning":     (
            f"Rule-based plan: {question_type} with metric={metric}, "
            f"dimension={primary_dim}, target={target_var}."
        ),
        "_source": "rule_based",
    }


# ── public API ────────────────────────────────────────────────────

def build_analysis_plan(
    query_intent: dict[str, Any],
    schema_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Main entry point.
    Returns an AnalysisPlan dict. Always succeeds.
    """
    if _llm_available():
        msg = _build_planner_message(query_intent, schema_profile)
        raw = _call_llm(_PLANNER_SYSTEM, msg)
        if raw:
            plan = _parse_llm_plan(raw)
            if plan and plan.get("operations"):
                plan["_source"] = "llm"
                return plan
        logger.info("LLM planner failed — falling back to rule-based plan.")

    return _rule_based_plan(query_intent, schema_profile)