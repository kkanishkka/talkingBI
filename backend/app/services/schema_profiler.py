from __future__ import annotations

from typing import Any
import pandas as pd


def _safe_sample_values(series: pd.Series, limit: int = 5) -> list[Any]:
    """Return up to `limit` non-null unique sample values."""
    values = series.dropna().unique().tolist()
    return values[:limit]


def _infer_role(series: pd.Series, dtype_str: str) -> str:
    """Infer a simple BI role for a column."""
    col = series.name.lower()

    if "date" in col or "time" in col:
        return "date"

    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"

    if pd.api.types.is_numeric_dtype(series):
        return "metric"

    return "dimension"


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Generate a schema profile for a dataframe."""
    columns_profile: list[dict[str, Any]] = []

    for column in df.columns:
        series = df[column]
        dtype_str = str(series.dtype)
        null_count = int(series.isna().sum())
        total_count = len(series)
        null_pct = round((null_count / total_count) * 100, 2) if total_count > 0 else 0.0
        unique_count = int(series.nunique(dropna=True))

        col_profile = {
            "name": column,
            "dtype": dtype_str,
            "role": _infer_role(series, dtype_str),
            "null_count": null_count,
            "null_percentage": null_pct,
            "unique_count": unique_count,
            "sample_values": _safe_sample_values(series),
        }

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