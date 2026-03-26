"""
app/services/schema_profiler.py
────────────────────────────────────────────────────────────────────
Profiles a DataFrame into a structured schema dict used downstream
by chart_recommender, insight_engine, and the /dashboard endpoint.

Improvements:
  - Stricter datetime detection
  - Prevents plain 'day', 'month', 'year', 'pdays' style fields from
    being wrongly classified as temporal
  - Adds min/max/mean/median/std for metrics
  - Adds top_values for dimensions
  - Better BI role inference for IDs, booleans, low-cardinality numerics
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from typing import Any
import pandas as pd


# ── helpers ───────────────────────────────────────────────────────


def _try_parse_datetime(series: pd.Series) -> bool:
    """
    Return True if the series looks like a real datetime field.

    Rules:
    - Only object/string-like columns are eligible
    - At least 80% of a sample must parse successfully
    - Reject simple numeric-like values such as 1, 2, 3... that pandas may
      incorrectly interpret as timestamps
    """
    if series.empty:
        return False

    # Only try parsing string/object columns
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return False

    sample = series.dropna().astype(str).str.strip()
    if len(sample) == 0:
        return False

    sample = sample.head(100)

    # Reject purely numeric-looking values like "1", "12", "365"
    # These are often codes / counts, not real dates
    numeric_like_ratio = sample.str.fullmatch(r"-?\d+(\.\d+)?").mean()
    if numeric_like_ratio > 0.8:
        return False

    # Parse dates
    try:
        parsed = pd.to_datetime(sample, errors="coerce")
        success_ratio = parsed.notna().mean()
        return success_ratio > 0.8
    except Exception:
        return False


def _safe_sample_values(series: pd.Series, limit: int = 5) -> list[Any]:
    """Return up to `limit` non-null unique sample values."""
    values = series.dropna().unique().tolist()
    return [v for v in values[:limit]]


def _top_values(series: pd.Series, limit: int = 5) -> list[dict[str, Any]]:
    """Return top-N values by frequency for a categorical series."""
    vc = series.value_counts(dropna=True).head(limit)
    return [{"value": str(k), "count": int(v)} for k, v in vc.items()]


def _infer_role(series: pd.Series) -> str:
    """
    Infer a BI role from the column name and dtype.
    Returns: 'date' | 'metric' | 'dimension'
    """
    col = series.name.lower().strip() if isinstance(series.name, str) else ""

    # Explicit identifier hints
    id_keywords = ("_id", "_key", "rownum", "index")
    if col == "id" or any(col.endswith(k) for k in id_keywords):
        return "dimension"

    # Strong date name hints only
    # Avoid treating plain day/month/year columns as true dates
    strong_date_keywords = (
        "date",
        "timestamp",
        "datetime",
        "created_at",
        "updated_at",
        "modified_at",
        "event_time",
        "order_date",
    )
    if any(kw in col for kw in strong_date_keywords):
        return "date"

    # Explicitly avoid misclassifying these as dates
    non_date_temporal_like = {"day", "month", "year", "weekday", "week", "quarter", "pdays"}
    if col in non_date_temporal_like:
        if pd.api.types.is_numeric_dtype(series):
            return "metric"
        return "dimension"

    # Dtype-based detection
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"

    if pd.api.types.is_bool_dtype(series):
        return "dimension"

    if pd.api.types.is_numeric_dtype(series):
        unique_count = series.nunique(dropna=True)
        total_non_null = series.count()

        # low-cardinality numeric columns often behave like categories
        if unique_count > 0 and unique_count <= 10 and total_non_null > 0:
            unique_ratio = unique_count / total_non_null
            if unique_ratio < 0.05:
                return "dimension"

        return "metric"

    # object / string columns → cautious datetime parse
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        if _try_parse_datetime(series):
            return "date"
        return "dimension"

    return "dimension"


# ── public API ────────────────────────────────────────────────────


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Generate a rich schema profile for a DataFrame."""
    columns_profile: list[dict[str, Any]] = []

    for column in df.columns:
        series = df[column]
        total_count = len(series)
        null_count = int(series.isna().sum())
        null_pct = round((null_count / total_count) * 100, 2) if total_count > 0 else 0.0
        unique_count = int(series.nunique(dropna=True))
        role = _infer_role(series)
        dtype_str = str(series.dtype)

        col_profile: dict[str, Any] = {
            "name": column,
            "dtype": dtype_str,
            "role": role,
            "null_count": null_count,
            "null_percentage": null_pct,
            "unique_count": unique_count,
            "sample_values": _safe_sample_values(series),
        }

        # extra stats per role
        if role == "metric":
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            if len(numeric) > 0:
                col_profile["min"] = round(float(numeric.min()), 4)
                col_profile["max"] = round(float(numeric.max()), 4)
                col_profile["mean"] = round(float(numeric.mean()), 4)
                col_profile["median"] = round(float(numeric.median()), 4)
                col_profile["std"] = round(float(numeric.std()), 4)

        elif role == "dimension":
            col_profile["top_values"] = _top_values(series)

        columns_profile.append(col_profile)

    dataset_summary = {
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_names": df.columns.tolist(),
    }

    return {
        "dataset_summary": dataset_summary,
        "columns": columns_profile,
    }