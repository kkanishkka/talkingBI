"""
app/services/schema_profiler.py
══════════════════════════════════════════════════════════════════════
Profiles a DataFrame into a rich SchemaContext.

Changes from original:
  - Fixes pd.to_datetime warning: uses format="mixed" for pandas ≥2.0
  - Avoids misclassifying day/month/year/pdays as date columns
  - Adds skew to metric stats
  - Enriches every column with semantic_hint via semantic_classifier
  - Returns both a plain dict (backward-compat) AND a SchemaContext object
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import warnings
from typing import Any

import pandas as pd

from app.core.models import ColumnProfile, ColumnRole, SchemaContext, SemanticHint
from app.services.semantic_classifier import classify_all_columns


# ── helpers ───────────────────────────────────────────────────────

def _try_parse_datetime(series: pd.Series) -> bool:
    """
    Return True if the series is genuinely a datetime field.
    Fixes: suppresses the pandas 'Could not infer format' FutureWarning
    by using format='mixed' (pandas ≥2.0) or errors='coerce' + ratio check.
    """
    if series.empty:
        return False
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return False

    sample = series.dropna().astype(str).str.strip().head(100)
    if len(sample) == 0:
        return False

    # Reject purely numeric-looking strings — these are counts, not dates
    numeric_ratio = sample.str.fullmatch(r"-?\d+(\.\d+)?").mean()
    if numeric_ratio > 0.8:
        return False

    try:
        # pandas ≥2.0: format="mixed" avoids the FutureWarning
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        return parsed.notna().mean() > 0.80
    except TypeError:
        # pandas <2.0 fallback
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                parsed = pd.to_datetime(sample, errors="coerce", infer_datetime_format=True)
            return parsed.notna().mean() > 0.80
        except Exception:
            return False


_NON_DATE_TEMPORAL = frozenset({
    "day", "month", "year", "weekday", "week", "quarter",
    "pdays", "hour", "minute", "second",
})

_STRONG_DATE_KEYWORDS = (
    "date", "timestamp", "datetime", "created_at", "updated_at",
    "modified_at", "event_time", "order_date", "purchase_date",
)

_ID_SUFFIXES = ("_id", "_key", "_code")


def _infer_role(series: pd.Series) -> ColumnRole:
    col = series.name.lower().strip() if isinstance(series.name, str) else ""

    # Explicit identifier
    if col == "id" or any(col.endswith(s) for s in _ID_SUFFIXES) or col in ("rownum", "index"):
        return ColumnRole.dimension  # keep as dim so it's not used as a metric

    # Strong date name hints
    if any(kw in col for kw in _STRONG_DATE_KEYWORDS):
        return ColumnRole.date

    # Avoid misclassifying plain numeric temporal-like columns
    if col in _NON_DATE_TEMPORAL:
        return ColumnRole.metric if pd.api.types.is_numeric_dtype(series) else ColumnRole.dimension

    # Actual datetime dtype
    if pd.api.types.is_datetime64_any_dtype(series):
        return ColumnRole.date

    # Boolean → dimension
    if pd.api.types.is_bool_dtype(series):
        return ColumnRole.dimension

    # Numeric
    if pd.api.types.is_numeric_dtype(series):
        unique_count  = series.nunique(dropna=True)
        total_non_null = series.count()
        if total_non_null > 0 and unique_count > 0:
            if unique_count <= 10 and (unique_count / total_non_null) < 0.05:
                return ColumnRole.dimension
        return ColumnRole.metric

    # Object/string → try datetime parse
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        if _try_parse_datetime(series):
            return ColumnRole.date
        return ColumnRole.dimension

    return ColumnRole.dimension


def _safe_sample(series: pd.Series, limit: int = 5) -> list[Any]:
    return series.dropna().unique().tolist()[:limit]


def _top_values(series: pd.Series, limit: int = 8) -> list[dict[str, Any]]:
    vc = series.value_counts(dropna=True).head(limit)
    return [{"value": str(k), "count": int(v)} for k, v in vc.items()]


# ── public API ────────────────────────────────────────────────────

def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """
    Profile a DataFrame and return a plain dict (backward-compatible).
    Also enriches with semantic_hint via semantic_classifier.
    """
    columns_profile: list[dict[str, Any]] = []
    total_rows = len(df)

    for column in df.columns:
        series = df[column]
        null_count  = int(series.isna().sum())
        null_pct    = round((null_count / total_rows) * 100, 2) if total_rows > 0 else 0.0
        unique_count = int(series.nunique(dropna=True))
        role        = _infer_role(series)
        dtype_str   = str(series.dtype)

        col_profile: dict[str, Any] = {
            "name":            column,
            "dtype":           dtype_str,
            "role":            role.value,
            "null_count":      null_count,
            "null_percentage": null_pct,
            "unique_count":    unique_count,
            "sample_values":   _safe_sample(series),
            "semantic_hint":   "none",  # will be overwritten below
        }

        if role == ColumnRole.dimension:
            col_profile["top_values"] = _top_values(series)

        elif role == ColumnRole.metric:
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            if len(numeric) > 0:
                col_profile.update({
                    "min":    round(float(numeric.min()),    4),
                    "max":    round(float(numeric.max()),    4),
                    "mean":   round(float(numeric.mean()),   4),
                    "median": round(float(numeric.median()), 4),
                    "std":    round(float(numeric.std()),    4),
                    "skew":   round(float(numeric.skew()),   4),
                })

        columns_profile.append(col_profile)

    # enrich with semantic hints
    columns_profile = classify_all_columns(columns_profile, total_rows)

    dataset_summary = {
        "rows":         int(df.shape[0]),
        "columns":      int(df.shape[1]),
        "column_names": df.columns.tolist(),
    }

    return {
        "dataset_summary": dataset_summary,
        "columns":         columns_profile,
    }


def build_schema_context(profile: dict[str, Any]) -> SchemaContext:
    """Convert a plain profile dict into a typed SchemaContext object."""
    summary  = profile["dataset_summary"]
    col_list = []
    for c in profile["columns"]:
        try:
            role = ColumnRole(c["role"])
        except ValueError:
            role = ColumnRole.dimension
        try:
            hint = SemanticHint(c.get("semantic_hint", "none"))
        except ValueError:
            hint = SemanticHint.none

        col_list.append(ColumnProfile(
            name=            c["name"],
            dtype=           c.get("dtype", "object"),
            role=            role,
            semantic_hint=   hint,
            null_count=      c.get("null_count", 0),
            null_percentage= c.get("null_percentage", 0.0),
            unique_count=    c.get("unique_count", 0),
            sample_values=   c.get("sample_values", []),
            top_values=      c.get("top_values", []),
            min=             c.get("min"),
            max=             c.get("max"),
            mean=            c.get("mean"),
            median=          c.get("median"),
            std=             c.get("std"),
            skew=            c.get("skew"),
        ))

    return SchemaContext(
        rows=         summary["rows"],
        columns=      summary["columns"],
        column_names= summary["column_names"],
        column_profiles= col_list,
    )