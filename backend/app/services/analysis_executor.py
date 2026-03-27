"""
app/services/analysis_executor.py
════════════════════════════════════════════════════════════════════
Agent 3: Analysis Executor

Responsibility:
  Execute an AnalysisPlan against a pandas DataFrame.
  This module is FULLY DETERMINISTIC — no LLM, no inference.

  It converts the plan's operation list into pandas calls and returns
  an ExecutionResult with chart-ready data.

  Supported operations:
    filter         → df[condition]
    groupby_agg    → df.groupby().agg() supporting rate/count/mean/sum/median
    value_counts   → series.value_counts()
    sort           → df.sort_values()
    top_n          → df.head(n)
    time_resample  → df.resample() after datetime parsing

  The key insight: rate is computed as mean(col == value), which is
  mathematically correct for binary variables, NOT as count.

Usage:
  from app.services.analysis_executor import execute_plan
  result = execute_plan(plan, df)
════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ── operation handlers ────────────────────────────────────────────

def _op_filter(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    col      = args["column"]
    operator = args.get("operator", "==")
    value    = args["value"]

    if col not in df.columns:
        logger.warning("filter: column '%s' not found, skipping", col)
        return df

    series = df[col]

    # try numeric coercion if the column is numeric
    if pd.api.types.is_numeric_dtype(series):
        try:
            value = float(value)
        except (ValueError, TypeError):
            pass

    ops = {
        "==":  lambda s, v: s == v,
        "!=":  lambda s, v: s != v,
        ">":   lambda s, v: s > v,
        ">=":  lambda s, v: s >= v,
        "<":   lambda s, v: s < v,
        "<=":  lambda s, v: s <= v,
    }
    if operator not in ops:
        logger.warning("filter: unknown operator '%s', skipping", operator)
        return df

    mask = ops[operator](series, value)
    filtered = df[mask]
    logger.debug("filter: %s %s %s → %d rows", col, operator, value, len(filtered))
    return filtered


def _op_groupby_agg(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    group_by   = args["group_by"]      # list of column names
    target     = args["target"]
    agg_fn     = args["agg_fn"]        # rate|count|mean|sum|median|max|min
    rate_value = args.get("rate_value", "yes")

    # validate columns
    missing = [c for c in group_by if c not in df.columns]
    if missing:
        raise ValueError(f"groupby_agg: columns not found: {missing}")

    if agg_fn == "count":
        # count of rows per group
        result = (
            df.groupby(group_by)
            .size()
            .reset_index(name="value")
        )

    elif agg_fn == "rate":
        # ── THE KEY FIX ──────────────────────────────────────────
        # Rate = proportion of rows where target == rate_value
        # This is correct: mean of a boolean, NOT count.
        # Prevents the classic "count vs rate" confusion.
        if target not in df.columns:
            raise ValueError(f"groupby_agg rate: target column '{target}' not found")

        binary = (df[target].astype(str).str.lower() == str(rate_value).lower()).astype(float)
        temp = df.copy()
        temp["_binary"] = binary

        result = (
            temp.groupby(group_by)["_binary"]
            .mean()
            .reset_index(name="value")
        )
        # round to 4 decimal places for readability
        result["value"] = result["value"].round(4)

    elif agg_fn in ("mean", "sum", "median", "max", "min"):
        if target not in df.columns:
            raise ValueError(f"groupby_agg {agg_fn}: target column '{target}' not found")

        numeric = pd.to_numeric(df[target], errors="coerce")
        temp    = df.copy()
        temp["_numeric"] = numeric

        agg_map = {
            "mean":   "mean",
            "sum":    "sum",
            "median": "median",
            "max":    "max",
            "min":    "min",
        }
        result = (
            temp.groupby(group_by)["_numeric"]
            .agg(agg_map[agg_fn])
            .reset_index(name="value")
        )
        result["value"] = result["value"].round(4)

    else:
        raise ValueError(f"groupby_agg: unsupported agg_fn '{agg_fn}'")

    # convert group columns to string for safe JSON serialisation
    for col in group_by:
        result[col] = result[col].astype(str)

    return result


def _op_value_counts(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    col       = args["column"]
    normalize = args.get("normalize", False)

    if col not in df.columns:
        raise ValueError(f"value_counts: column '{col}' not found")

    vc = df[col].value_counts(normalize=normalize, dropna=True)
    result = vc.reset_index()
    result.columns = [col, "value"]
    result[col] = result[col].astype(str)
    if normalize:
        result["value"] = result["value"].round(4)
    return result


def _op_sort(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    by        = args.get("by", "value")
    ascending = args.get("ascending", False)

    if by not in df.columns:
        # try to sort by the last non-group column
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            by = numeric_cols[-1]
        else:
            logger.warning("sort: column '%s' not found, skipping sort", by)
            return df

    return df.sort_values(by=by, ascending=ascending).reset_index(drop=True)


def _op_top_n(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    n = int(args.get("n", 10))
    return df.head(n)


def _op_time_resample(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    date_col = args["date_col"]
    freq     = args.get("freq", "M")
    target   = args.get("target")
    agg_fn   = args.get("agg_fn", "count")

    if date_col not in df.columns:
        raise ValueError(f"time_resample: date column '{date_col}' not found")

    temp = df.copy()
    temp["_dt"] = pd.to_datetime(temp[date_col], errors="coerce")
    temp = temp.dropna(subset=["_dt"])

    if temp.empty:
        return pd.DataFrame(columns=[date_col, "value"])

    temp = temp.set_index("_dt")

    if target and target in temp.columns and agg_fn != "count":
        numeric = pd.to_numeric(temp[target], errors="coerce")
        if agg_fn == "sum":
            result = numeric.resample(freq).sum()
        elif agg_fn == "mean":
            result = numeric.resample(freq).mean()
        else:
            result = numeric.resample(freq).count()
    else:
        result = temp.resample(freq).size()

    result = result.reset_index()
    result.columns = [date_col, "value"]
    result[date_col] = result[date_col].astype(str)
    result["value"]  = result["value"].round(4)
    return result


# ── operation dispatcher ──────────────────────────────────────────

_OP_HANDLERS = {
    "filter":        _op_filter,
    "groupby_agg":   _op_groupby_agg,
    "value_counts":  _op_value_counts,
    "sort":          _op_sort,
    "top_n":         _op_top_n,
    "time_resample": _op_time_resample,
}


# ── public API ────────────────────────────────────────────────────

def execute_plan(
    plan: dict[str, Any],
    df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Execute an AnalysisPlan against a DataFrame.

    Returns an ExecutionResult:
    {
        "success": bool,
        "data": list[dict],      ← chart-ready rows
        "x_field": str,
        "y_field": str,
        "row_count": int,
        "metric_label": str,
        "result_label": str,
        "error": str | None,
    }
    """
    operations   = plan.get("operations", [])
    x_field      = plan.get("x_field", "")
    y_field      = plan.get("y_field", "value")
    metric_label = plan.get("metric_label", "Value")
    result_label = plan.get("result_label", "Analysis Result")

    current_df = df.copy()

    for op_spec in sorted(operations, key=lambda o: o.get("step", 0)):
        op   = op_spec.get("op")
        args = op_spec.get("args", {})

        handler = _OP_HANDLERS.get(op)
        if handler is None:
            logger.warning("execute_plan: unknown op '%s', skipping", op)
            continue

        try:
            current_df = handler(current_df, args)
        except Exception as exc:
            logger.error("execute_plan: op '%s' failed: %s", op, exc)
            return {
                "success":      False,
                "data":         [],
                "x_field":      x_field,
                "y_field":      y_field,
                "row_count":    0,
                "metric_label": metric_label,
                "result_label": result_label,
                "error":        f"Operation '{op}' failed: {exc}",
            }

    # convert to records, handle NaN
    try:
        records = (
            current_df
            .replace({float("nan"): None, float("inf"): None, float("-inf"): None})
            .to_dict(orient="records")
        )
    except Exception as exc:
        records = []
        logger.error("execute_plan: failed to serialise result: %s", exc)

    return {
        "success":      True,
        "data":         records,
        "x_field":      x_field,
        "y_field":      y_field,
        "row_count":    len(records),
        "metric_label": metric_label,
        "result_label": result_label,
        "error":        None,
    }