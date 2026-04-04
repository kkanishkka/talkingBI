"""
app/layers/reasoning/analysis_executor.py
══════════════════════════════════════════════════════════════════════
Deterministic Pandas Executor — v2

Change from v1:
  ① Added scalar_agg operation — the KPI path.
    scalar_agg computes a single aggregate over a column (or row count)
    and returns ONE row: {"metric": "<label>", "value": <number>}
    This enables "total revenue" → {"metric": "Total Revenue", "value": 94328.0}
    without any grouping.

All other operations are UNCHANGED. The executor remains purely
deterministic — zero LLM calls.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.models import AnalysisPlan, ExecutionResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — operation handlers
# ═══════════════════════════════════════════════════════════════════

def _op_filter(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    col = args["column"]
    op  = args.get("operator", "==")
    val = args["value"]
    if col not in df.columns:
        logger.warning("filter: column '%s' not in df, skipping", col)
        return df
    series = df[col]
    if pd.api.types.is_numeric_dtype(series):
        try:
            val = float(val)
        except (TypeError, ValueError):
            pass
    ops = {
        "==":     lambda s, v: s == v,
        "!=":     lambda s, v: s != v,
        ">":      lambda s, v: s > v,
        ">=":     lambda s, v: s >= v,
        "<":      lambda s, v: s < v,
        "<=":     lambda s, v: s <= v,
        "in":     lambda s, v: s.isin(v if isinstance(v, list) else [v]),
        "not_in": lambda s, v: ~s.isin(v if isinstance(v, list) else [v]),
    }
    fn = ops.get(op)
    if fn is None:
        logger.warning("filter: unknown operator '%s', skipping", op)
        return df
    return df[fn(series, val)]


def _op_scalar_agg(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    """
    NEW: Compute a single scalar aggregate over the whole dataframe column.
    Returns a 1-row DataFrame: {"metric": "<label>", "value": <number>}

    This is the KPI path — no grouping, no chart, just a number.

    args:
      target: column name to aggregate (None → count rows)
      agg_fn: count | sum | mean | median | max | min
    """
    target = args.get("target")
    agg_fn = args.get("agg_fn", "count")

    if agg_fn == "count" or target is None:
        result_value = len(df)
        metric_label = "Row Count"
    else:
        if target not in df.columns:
            raise ValueError(f"scalar_agg: column '{target}' not found in dataframe")
        numeric = pd.to_numeric(df[target], errors="coerce").dropna()
        if len(numeric) == 0:
            raise ValueError(
                f"scalar_agg: column '{target}' has no numeric values after coercion"
            )
        agg_fns = {
            "sum":    numeric.sum,
            "mean":   numeric.mean,
            "median": numeric.median,
            "max":    numeric.max,
            "min":    numeric.min,
        }
        fn = agg_fns.get(agg_fn)
        if fn is None:
            raise ValueError(f"scalar_agg: unsupported agg_fn '{agg_fn}'")
        result_value = round(float(fn()), 4)
        metric_label = f"{agg_fn.title()} of {target.replace('_', ' ').title()}"

    return pd.DataFrame([{"metric": metric_label, "value": result_value}])


def _op_groupby_agg(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    group_by   = args["group_by"]
    target     = args["target"]
    agg_fn     = args["agg_fn"]
    rate_value = args.get("rate_value", "yes")

    missing = [c for c in group_by if c not in df.columns]
    if missing:
        raise ValueError(f"groupby_agg: columns not found: {missing}")

    if agg_fn == "count":
        result = df.groupby(group_by).size().reset_index(name="value")
    elif agg_fn == "rate":
        if target not in df.columns:
            raise ValueError(f"groupby_agg rate: target '{target}' not found")
        binary = (df[target].astype(str).str.strip().str.lower()
                  == str(rate_value).strip().lower()).astype(float)
        tmp = df.copy()
        tmp["_binary"] = binary
        result = tmp.groupby(group_by)["_binary"].mean().reset_index(name="value")
        result["value"] = result["value"].round(4)
    elif agg_fn in ("mean", "sum", "median", "max", "min"):
        if target not in df.columns:
            raise ValueError(f"groupby_agg {agg_fn}: target '{target}' not found")
        numeric = pd.to_numeric(df[target], errors="coerce")
        tmp = df.copy()
        tmp["_num"] = numeric
        result = tmp.groupby(group_by)["_num"].agg(agg_fn).reset_index(name="value")
        result["value"] = result["value"].round(4)
    else:
        raise ValueError(f"groupby_agg: unsupported agg_fn '{agg_fn}'")

    for col in group_by:
        result[col] = result[col].astype(str)
    return result


def _op_value_counts(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    col       = args["column"]
    normalize = args.get("normalize", False)
    if col not in df.columns:
        raise ValueError(f"value_counts: column '{col}' not found")
    vc     = df[col].value_counts(normalize=normalize, dropna=True)
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
        numeric = df.select_dtypes(include="number").columns.tolist()
        by = numeric[-1] if numeric else df.columns[-1]
    return df.sort_values(by=by, ascending=ascending).reset_index(drop=True)


def _op_top_n(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    return df.head(int(args.get("n", 10)))


def _op_time_resample(df: pd.DataFrame, args: dict[str, Any]) -> pd.DataFrame:
    date_col = args["date_col"]
    freq     = args.get("freq", "M")
    target   = args.get("target")
    agg_fn   = args.get("agg_fn", "count")
    if date_col not in df.columns:
        raise ValueError(f"time_resample: date column '{date_col}' not found")
    tmp = df.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            tmp["_dt"] = pd.to_datetime(tmp[date_col], errors="coerce", format="mixed")
        except TypeError:
            tmp["_dt"] = pd.to_datetime(tmp[date_col], errors="coerce",
                                         infer_datetime_format=True)
    tmp = tmp.dropna(subset=["_dt"]).set_index("_dt")
    if not tmp.empty:
        if target and target in tmp.columns and agg_fn != "count":
            num = pd.to_numeric(tmp[target], errors="coerce")
            resampled = getattr(num.resample(freq), agg_fn)()
        else:
            resampled = tmp.resample(freq).size()
        result = resampled.reset_index()
        result.columns = [date_col, "value"]
        result[date_col] = result[date_col].astype(str)
        result["value"]  = result["value"].round(4)
        return result
    return pd.DataFrame(columns=[date_col, "value"])


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — op dispatch table
# ═══════════════════════════════════════════════════════════════════

_OP_MAP = {
    "filter":        _op_filter,
    "scalar_agg":    _op_scalar_agg,      # NEW
    "groupby_agg":   _op_groupby_agg,
    "value_counts":  _op_value_counts,
    "sort":          _op_sort,
    "top_n":         _op_top_n,
    "time_resample": _op_time_resample,
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — public API
# ═══════════════════════════════════════════════════════════════════

def execute_plan(plan: AnalysisPlan, df: pd.DataFrame) -> ExecutionResult:
    """Execute an AnalysisPlan deterministically. Never calls LLM."""
    sample_warning: str | None = None

    if len(df) > settings.max_df_rows:
        df = df.sample(n=settings.sample_rows, random_state=42)
        sample_warning = (
            f"Dataset sampled to {settings.sample_rows:,} rows for performance. "
            f"Results are statistically representative."
        )
        logger.warning("execute_plan: df sampled to %d rows", settings.sample_rows)

    current_df          = df.copy()
    intermediate_counts = {"input": len(current_df)}

    for op_spec in sorted(plan.operations, key=lambda o: o.step):
        handler = _OP_MAP.get(op_spec.op)
        if handler is None:
            logger.warning("execute_plan: unknown op '%s', skipping", op_spec.op)
            continue
        try:
            current_df = handler(current_df, op_spec.args)
            intermediate_counts[
                f"after_{op_spec.op}_step{op_spec.step}"
            ] = len(current_df)
        except Exception as exc:
            logger.error("execute_plan: op '%s' failed: %s", op_spec.op, exc)
            return ExecutionResult(
                success=False, data=[], x_field=plan.x_field, y_field=plan.y_field,
                row_count=0, metric_label=plan.metric_label, result_label=plan.result_label,
                intermediate_counts=intermediate_counts,
                error=f"Operation '{op_spec.op}' (step {op_spec.step}) failed: {exc}",
                sample_warning=sample_warning,
            )

    try:
        records = (
            current_df
            .replace({float("nan"): None, float("inf"): None, float("-inf"): None})
            .to_dict(orient="records")
        )
    except Exception as exc:
        records = []
        logger.error("execute_plan: serialization failed: %s", exc)

    return ExecutionResult(
        success=True, data=records,
        x_field=plan.x_field, y_field=plan.y_field,
        row_count=len(records),
        metric_label=plan.metric_label, result_label=plan.result_label,
        intermediate_counts=intermediate_counts, error=None,
        sample_warning=sample_warning,
    )