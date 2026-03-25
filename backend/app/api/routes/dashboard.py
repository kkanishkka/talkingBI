"""
app/api/routes/dashboard.py
────────────────────────────────────────────────────────────────────
Single combined endpoint that:
  1. Receives an uploaded file + optional natural-language prompt
  2. Profiles the schema  (schema_profiler)
  3. Parses intent        (intent_parser)
  4. Recommends charts    (chart_recommender)
  5. Generates insights   (insight_engine)
  6. Materialises chart-ready data from the actual DataFrame
  7. Returns one clean JSON response the frontend can render generically

No existing service is rewritten — this router is the only new file.
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.schema_profiler import profile_dataframe
from app.services.intent_parser import parse_intent
from app.services.chart_recommender import recommend_charts
from app.services.insight_engine import generate_insights

router = APIRouter(tags=["dashboard"])


# ── helpers ──────────────────────────────────────────────────────────


def _load_dataframe(file: UploadFile) -> pd.DataFrame:
    filename = file.filename or ""
    ext = filename.lower().rsplit(".", 1)[-1]
    raw = file.file.read()
    if ext == "csv":
        return pd.read_csv(io.BytesIO(raw))
    if ext in {"xlsx", "xls"}:
        return pd.read_excel(io.BytesIO(raw))
    raise HTTPException(
        status_code=400,
        detail="Unsupported file type. Please upload a CSV or Excel file.",
    )


def _materialise_chart_data(
    chart: dict[str, Any],
    df: pd.DataFrame,
    schema_profile: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Turn a chart spec from chart_recommender into a visualization object
    that contains actual aggregated data the frontend can render directly.

    Returns a dict with:
      chart_type, title, x_field, y_field (bar/line/histogram)
      OR label_field, value_field (pie / donut)
      data: list[dict]   ← chart-ready rows
    """
    chart_type = chart.get("chart_type", "bar")
    fields = chart.get("fields", [])
    if not fields:
        return None

    primary_field = fields[0]
    if primary_field not in df.columns:
        return None

    # ── find companion numeric field (first metric column that isn't primary) ──
    metric_field: str | None = None
    for col_info in schema_profile.get("columns", []):
        if col_info["role"] == "metric" and col_info["name"] != primary_field:
            metric_field = col_info["name"]
            break

    series = df[primary_field]

    # ── line chart — time-series ────────────────────────────────────
    if chart_type == "line":
        try:
            df["_dt"] = pd.to_datetime(series, errors="coerce")
            grouped = df.dropna(subset=["_dt"])
            if metric_field:
                agg = (
                    grouped.groupby("_dt")[metric_field]
                    .sum()
                    .reset_index()
                    .rename(columns={"_dt": primary_field, metric_field: "value"})
                    .sort_values(primary_field)
                )
                agg[primary_field] = agg[primary_field].astype(str)
                data = agg.to_dict(orient="records")
            else:
                agg = (
                    grouped.groupby("_dt")
                    .size()
                    .reset_index(name="value")
                    .rename(columns={"_dt": primary_field})
                    .sort_values(primary_field)
                )
                agg[primary_field] = agg[primary_field].astype(str)
                data = agg.to_dict(orient="records")
            df.drop(columns=["_dt"], inplace=True, errors="ignore")
        except Exception:
            return None

        return {
            "chart_type": "line",
            "title": chart["title"],
            "x_field": primary_field,
            "y_field": "value",
            "data": data,
        }

    # ── bar / horizontal_bar — categorical counts or metric aggregation ─
    if chart_type in {"bar", "horizontal_bar"}:
        if metric_field:
            agg = (
                df.groupby(primary_field)[metric_field]
                .sum()
                .reset_index()
                .rename(columns={metric_field: "value"})
                .sort_values("value", ascending=False)
                .head(20)
            )
        else:
            agg = (
                df[primary_field]
                .value_counts()
                .reset_index()
                .rename(columns={"count": "value", primary_field: primary_field})
                .head(20)
            )
            # pandas ≥2 value_counts returns "count" column
            if "count" in agg.columns:
                agg = agg.rename(columns={"count": "value"})
            if "value" not in agg.columns:
                agg.columns = [primary_field, "value"]

        agg[primary_field] = agg[primary_field].astype(str)
        return {
            "chart_type": chart_type,
            "title": chart["title"],
            "x_field": primary_field,
            "y_field": "value",
            "data": agg.to_dict(orient="records"),
        }

    # ── histogram — numeric distribution ───────────────────────────
    if chart_type == "histogram":
        numeric_series = pd.to_numeric(series, errors="coerce").dropna()
        if numeric_series.empty:
            return None
        bins = min(10, numeric_series.nunique())
        counts, edges = pd.cut(numeric_series, bins=bins, retbins=True)
        bin_labels = [
            f"{round(edges[i], 1)}–{round(edges[i+1], 1)}"
            for i in range(len(edges) - 1)
        ]
        bin_counts = counts.value_counts(sort=False).values.tolist()
        data = [{"range": lbl, "count": cnt} for lbl, cnt in zip(bin_labels, bin_counts)]
        return {
            "chart_type": "histogram",
            "title": chart["title"],
            "x_field": "range",
            "y_field": "count",
            "data": data,
        }

    # ── pie / donut ─────────────────────────────────────────────────
    if chart_type in {"pie", "donut"}:
        agg = (
            df[primary_field]
            .value_counts()
            .reset_index()
            .head(8)
        )
        if "count" in agg.columns:
            agg = agg.rename(columns={"count": "value"})
        if "value" not in agg.columns:
            agg.columns = [primary_field, "value"]
        agg[primary_field] = agg[primary_field].astype(str)
        return {
            "chart_type": "pie",
            "title": chart["title"],
            "label_field": primary_field,
            "value_field": "value",
            "data": agg.to_dict(orient="records"),
        }

    # ── kpi_card ────────────────────────────────────────────────────
    if chart_type == "kpi_card":
        numeric_series = pd.to_numeric(series, errors="coerce")
        return {
            "chart_type": "kpi_card",
            "title": chart["title"],
            "data": [
                {"metric": "sum",    "value": round(float(numeric_series.sum()), 2)},
                {"metric": "mean",   "value": round(float(numeric_series.mean()), 2)},
                {"metric": "median", "value": round(float(numeric_series.median()), 2)},
                {"metric": "max",    "value": round(float(numeric_series.max()), 2)},
            ],
        }

    return None


# ── main endpoint ─────────────────────────────────────────────────────


@router.post("/dashboard")
async def generate_dashboard(
    file: UploadFile = File(...),
    prompt: str = Form(default="Give me a complete overview dashboard"),
):
    """
    Single entry-point for the TalkingBI frontend.
    Returns a fully self-contained dashboard payload.
    """
    # 1 — load data
    try:
        df = _load_dataframe(file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"File parsing failed: {exc}") from exc

    # 2 — profile schema
    schema_profile = profile_dataframe(df)

    # 3 — parse intent from the user prompt
    schema_columns = schema_profile["dataset_summary"]["column_names"]
    intent = parse_intent(prompt, schema_columns)

    # 4 — recommend charts (max 6)
    intent["num_visualizations"] = min(intent.get("num_visualizations", 4), 6)
    chart_specs = recommend_charts(intent, schema_profile)

    # 5 — materialise actual data for each chart spec
    visualizations: list[dict[str, Any]] = []
    for spec in chart_specs:
        viz = _materialise_chart_data(spec, df, schema_profile)
        if viz:
            viz["why_this_chart"] = spec.get("why_this_chart", "")
            viz["confidence"] = spec.get("confidence", 0.75)
            visualizations.append(viz)

    # 6 — generate insights
    insight_output = generate_insights(intent, chart_specs, schema_profile)

    # 7 — assemble final response
    return {
        "message": "Dashboard generated successfully.",
        "dataset_profile": {
            "rows": schema_profile["dataset_summary"]["rows"],
            "columns": schema_profile["dataset_summary"]["columns"],
            "column_names": schema_columns,
            "column_details": [
                {
                    "name": c["name"],
                    "dtype": c["dtype"],
                    "role": c["role"],
                    "unique_count": c["unique_count"],
                    "null_percentage": c["null_percentage"],
                }
                for c in schema_profile["columns"]
            ],
        },
        "executive_summary": insight_output["executive_summary"],
        "insights": insight_output["insights"],
        "visualizations": visualizations,
    }