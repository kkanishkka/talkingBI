"""
app/services/insight_engine.py
────────────────────────────────────────────────────────────────────
Generates data-driven, business-language insights from the schema
profile and chart specs.

NO hardcoded column names. Every observation is inferred from the
actual data statistics stored in schema_profile["columns"].
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from typing import Any


# ── internal helpers ──────────────────────────────────────────────


def _pct(part: float, whole: float) -> str:
    if whole == 0:
        return "0%"
    return f"{round((part / whole) * 100, 1)}%"


def _skew_label(skew: float) -> str:
    if skew > 1.0:
        return "strongly right-skewed (long tail of high values)"
    if skew > 0.5:
        return "moderately right-skewed"
    if skew < -1.0:
        return "strongly left-skewed (long tail of low values)"
    if skew < -0.5:
        return "moderately left-skewed"
    return "approximately symmetric"


def _imbalance_label(ratio: float) -> str:
    """ratio = count_of_top_category / total"""
    if ratio >= 0.70:
        return "heavily dominated"
    if ratio >= 0.50:
        return "moderately dominated"
    return "relatively balanced"


# ── per-column insight builders ───────────────────────────────────


def _insight_for_dimension(col: dict[str, Any], total_rows: int) -> dict[str, Any] | None:
    """
    Generate a business insight for a categorical (dimension) column.
    Uses: unique_count, null_percentage, sample_values.
    """
    name = col["name"]
    unique = col["unique_count"]
    null_pct = col["null_percentage"]
    sample = col.get("sample_values", [])

    observations: list[str] = []

    # cardinality observation
    if unique == 1:
        observations.append(
            f"**{name}** has only one unique value — this column carries no discriminatory power "
            f"and may not be useful for segmentation."
        )
        priority = "low"
    elif unique <= 5:
        cats = ", ".join(str(v) for v in sample[:unique])
        observations.append(
            f"**{name}** has {unique} distinct categories ({cats}), "
            f"making it ideal for segmentation and group comparison."
        )
        priority = "high"
    elif unique <= 20:
        observations.append(
            f"**{name}** contains {unique} distinct values — moderate cardinality suitable for "
            f"bar or pie charts with grouping."
        )
        priority = "medium"
    else:
        observations.append(
            f"**{name}** has high cardinality ({unique} unique values). "
            f"Consider grouping or filtering to the top-N categories before visualizing."
        )
        priority = "low"

    # null observation
    if null_pct > 10:
        observations.append(
            f"{null_pct}% of records are missing **{name}** — data quality should be reviewed "
            f"before drawing conclusions from this field."
        )
        priority = "high"

    if not observations:
        return None

    return {
        "title": f"{name} — Category Structure",
        "insight_text": " ".join(observations),
        "category": "distribution",
        "priority": priority,
        "evidence_fields": [name],
        "confidence": 0.85,
    }


def _insight_for_metric(col: dict[str, Any], total_rows: int) -> dict[str, Any] | None:
    """
    Generate a business insight for a numeric (metric) column.
    Uses: sample_values, null_percentage, unique_count.
    Falls back gracefully when summary stats are absent.
    """
    name = col["name"]
    null_pct = col["null_percentage"]
    sample = col.get("sample_values", [])

    # try to compute basic stats from sample values
    numeric_sample = []
    for v in sample:
        try:
            numeric_sample.append(float(v))
        except (TypeError, ValueError):
            pass

    observations: list[str] = []
    priority = "medium"

    if len(numeric_sample) >= 3:
        mn = min(numeric_sample)
        mx = max(numeric_sample)
        mean = sum(numeric_sample) / len(numeric_sample)
        observations.append(
            f"**{name}** ranges from {mn:,.2f} to {mx:,.2f} with an average of {mean:,.2f} "
            f"(based on sample values)."
        )
        spread = mx - mn
        if spread == 0:
            observations.append(
                f"All sampled values of **{name}** are identical — this field may be constant."
            )
            priority = "low"
        elif mx > 0 and (spread / mx) > 0.5:
            observations.append(
                f"The wide value spread ({spread:,.2f}) suggests significant variation in **{name}** "
                f"— outliers or distinct sub-groups likely exist."
            )
            priority = "high"
    elif len(numeric_sample) >= 1:
        observations.append(
            f"**{name}** is a numeric metric. Sample values: "
            f"{', '.join(f'{v:,.2f}' for v in numeric_sample)}."
        )

    if null_pct > 5:
        observations.append(
            f"{null_pct}% of **{name}** values are missing — imputation or exclusion "
            f"may be needed before using this metric in calculations."
        )
        priority = "high"

    if col["unique_count"] <= 5 and col["unique_count"] > 0:
        observations.append(
            f"**{name}** has only {col['unique_count']} distinct numeric values — "
            f"it may behave more like a categorical variable (e.g. a rating or flag)."
        )

    if not observations:
        observations.append(
            f"**{name}** is a numeric metric with {col['unique_count']} unique values. "
            f"Use this field in aggregations, histograms, or KPI cards."
        )

    return {
        "title": f"{name} — Metric Profile",
        "insight_text": " ".join(observations),
        "category": "descriptive",
        "priority": priority,
        "evidence_fields": [name],
        "confidence": 0.80,
    }


def _insight_for_date(col: dict[str, Any], total_rows: int) -> dict[str, Any] | None:
    name = col["name"]
    unique = col["unique_count"]
    null_pct = col["null_percentage"]
    sample = col.get("sample_values", [])

    observations: list[str] = []

    if unique > 1:
        date_range_hint = ""
        if len(sample) >= 2:
            date_range_hint = f" (sample range: {sample[0]} → {sample[-1]})"
        observations.append(
            f"**{name}** spans {unique} unique time points{date_range_hint}, "
            f"enabling time-series trend analysis."
        )
    else:
        observations.append(
            f"**{name}** has only {unique} distinct date — temporal analysis may be limited."
        )

    if null_pct > 0:
        observations.append(
            f"{null_pct}% of date values in **{name}** are missing — "
            f"these records will be excluded from time-series charts."
        )

    return {
        "title": f"{name} — Temporal Coverage",
        "insight_text": " ".join(observations),
        "category": "trend",
        "priority": "high" if unique > 5 else "medium",
        "evidence_fields": [name],
        "confidence": 0.88,
    }


# ── cross-column insights ─────────────────────────────────────────


def _cross_column_insights(
    schema_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Detect dataset-level patterns that span multiple columns.
    """
    columns = schema_profile.get("columns", [])
    summary = schema_profile.get("dataset_summary", {})
    total_rows = summary.get("rows", 0)
    total_cols = summary.get("columns", 0)

    insights: list[dict[str, Any]] = []

    metrics = [c for c in columns if c["role"] == "metric"]
    dimensions = [c for c in columns if c["role"] == "dimension"]
    dates = [c for c in columns if c["role"] == "date"]

    # data completeness
    high_null_cols = [c["name"] for c in columns if c["null_percentage"] > 15]
    if high_null_cols:
        insights.append({
            "title": "Data Quality Warning",
            "insight_text": (
                f"{len(high_null_cols)} column(s) have >15% missing values: "
                f"**{', '.join(high_null_cols)}**. "
                f"This may bias analysis and should be addressed before production reporting."
            ),
            "category": "data_quality",
            "priority": "high",
            "evidence_fields": high_null_cols,
            "confidence": 0.95,
        })

    # schema richness
    if metrics and dimensions:
        insights.append({
            "title": "Schema Mix — Analytical Potential",
            "insight_text": (
                f"The dataset contains {len(metrics)} metric(s) "
                f"({', '.join(m['name'] for m in metrics[:3])}) "
                f"and {len(dimensions)} dimension(s) "
                f"({', '.join(d['name'] for d in dimensions[:3])}). "
                f"This structure supports segmented metric analysis — "
                f"e.g., comparing averages of each metric across categories."
            ),
            "category": "structural",
            "priority": "medium",
            "evidence_fields": [c["name"] for c in metrics[:3] + dimensions[:3]],
            "confidence": 0.90,
        })

    if dates:
        insights.append({
            "title": "Time-Series Capability Detected",
            "insight_text": (
                f"The dataset includes {len(dates)} date/time field(s): "
                f"**{', '.join(d['name'] for d in dates)}**. "
                f"Trend charts can track how metrics evolve over time — "
                f"a strong signal for executive reporting."
            ),
            "category": "trend",
            "priority": "high",
            "evidence_fields": [d["name"] for d in dates],
            "confidence": 0.92,
        })

    # volume signal
    if total_rows < 100:
        insights.append({
            "title": "Small Dataset — Interpret With Caution",
            "insight_text": (
                f"The dataset contains only {total_rows} rows. "
                f"Statistical patterns may not be representative. "
                f"Results should be treated as exploratory rather than conclusive."
            ),
            "category": "data_quality",
            "priority": "medium",
            "evidence_fields": [],
            "confidence": 0.95,
        })
    elif total_rows > 100_000:
        insights.append({
            "title": "Large Dataset — Aggregation Recommended",
            "insight_text": (
                f"With {total_rows:,} rows, this dataset is large enough for statistically "
                f"robust conclusions. Aggregated views (sums, averages, percentages) will "
                f"be more readable than raw record plots."
            ),
            "category": "structural",
            "priority": "low",
            "evidence_fields": [],
            "confidence": 0.90,
        })

    return insights


# ── executive summary builder ─────────────────────────────────────


def _build_executive_summary(
    schema_profile: dict[str, Any],
    charts: list[dict[str, Any]],
    intent: dict[str, Any],
) -> list[str]:
    """
    Returns 3–5 bullet strings written in analytical business language.
    Each bullet answers: "so what?"
    """
    summary = schema_profile.get("dataset_summary", {})
    columns = schema_profile.get("columns", [])
    total_rows = summary.get("rows", 0)
    total_cols = summary.get("columns", 0)

    metrics = [c for c in columns if c["role"] == "metric"]
    dimensions = [c for c in columns if c["role"] == "dimension"]
    dates = [c for c in columns if c["role"] == "date"]

    high_null = [c for c in columns if c["null_percentage"] > 10]

    bullets: list[str] = []

    # bullet 1 — scope
    bullets.append(
        f"Dataset contains **{total_rows:,} records** across **{total_cols} fields**, "
        f"providing {('a broad' if total_cols > 6 else 'a focused')} view suitable for "
        f"{intent.get('business_goal', 'BI exploration')}."
    )

    # bullet 2 — analytical dimensions
    if dimensions:
        dim_names = ", ".join(f"**{d['name']}**" for d in dimensions[:4])
        bullets.append(
            f"{len(dimensions)} categorical dimension(s) identified — {dim_names} — "
            f"enabling segmentation and group-level comparison across the dataset."
        )

    # bullet 3 — metrics
    if metrics:
        metric_names = ", ".join(f"**{m['name']}**" for m in metrics[:4])
        bullets.append(
            f"{len(metrics)} quantitative metric(s) available — {metric_names} — "
            f"supporting aggregation, distribution analysis, and KPI tracking."
        )

    # bullet 4 — time series
    if dates:
        date_names = ", ".join(f"**{d['name']}**" for d in dates)
        bullets.append(
            f"Temporal field(s) detected ({date_names}), enabling trend analysis "
            f"and time-based performance tracking."
        )

    # bullet 5 — data quality
    if high_null:
        names = ", ".join(f"**{c['name']}**" for c in high_null[:3])
        bullets.append(
            f"⚠ Data quality flag: {len(high_null)} field(s) ({names}) contain >10% missing "
            f"values — review before using in critical calculations."
        )
    else:
        bullets.append(
            f"Data completeness looks healthy — no fields with significant missing values detected."
        )

    return bullets[:5]


# ── public API ────────────────────────────────────────────────────


def generate_insights(
    intent: dict[str, Any],
    charts: list[dict[str, Any]],
    schema_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Main entry point — called by both /dashboard and /generate-insights.

    Returns:
      {
        "executive_summary": list[str],   ← bullet strings
        "insights": list[dict],           ← per-field + cross-column
        "key_takeaways": list[str],       ← 1-liner per chart
      }
    """
    columns = schema_profile.get("columns", [])
    summary = schema_profile.get("dataset_summary", {})
    total_rows = summary.get("rows", 0)

    per_column_insights: list[dict[str, Any]] = []
    for col in columns:
        role = col.get("role")
        if role == "dimension":
            ins = _insight_for_dimension(col, total_rows)
        elif role == "metric":
            ins = _insight_for_metric(col, total_rows)
        elif role == "date":
            ins = _insight_for_date(col, total_rows)
        else:
            ins = None
        if ins:
            per_column_insights.append(ins)

    cross_insights = _cross_column_insights(schema_profile)

    # merge and rank: high → medium → low
    all_insights = per_column_insights + cross_insights
    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_insights.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 3))

    # keep top 8
    top_insights = all_insights[:8]

    executive_summary = _build_executive_summary(schema_profile, charts, intent)

    key_takeaways = []
    for chart in charts:
        fields = chart.get("fields", [])
        ctype = chart.get("chart_type", "chart")
        title = chart.get("title", "")
        if fields:
            key_takeaways.append(
                f"**{title}** — A {ctype} of **{fields[0]}** "
                f"{chart.get('what_it_shows', '').lower() or 'reveals its distribution and structure'}."
            )

    return {
        "executive_summary": executive_summary,
        "insights": top_insights,
        "key_takeaways": key_takeaways,
    }