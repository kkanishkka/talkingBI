"""
app/services/insight_engine.py
══════════════════════════════════════════════════════════════════════
Dataset-level insight generator.

Renamed public function: generate_dataset_insights()
(old name generate_insights() kept as alias for backward compatibility)

Removed:
  - _build_insight_from_chart() → produced "A bar chart is safe default" text
  - key_takeaways → replaced by InsightReport.bullets in narration agent

Kept and improved:
  - _cross_column_insights() — schema mix, data quality, volume signals
  - _build_executive_summary() — dataset scope bullets
  - Per-column structure insights (dimension cardinality, metric spread)
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any


# ── column-level insights ─────────────────────────────────────────

def _insight_for_dimension(col: dict[str, Any], total_rows: int) -> dict[str, Any] | None:
    name     = col["name"]
    unique   = col["unique_count"]
    null_pct = col["null_percentage"]
    sample   = col.get("sample_values", [])
    hint     = col.get("semantic_hint", "none")

    # skip identifiers
    if hint == "likely_id":
        return None

    obs: list[str] = []

    if hint == "likely_target":
        top = col.get("top_values", [])
        if top and len(top) >= 2:
            dominant = top[0]
            minority = top[-1]
            total = sum(t["count"] for t in top[:2])
            if total > 0:
                dom_pct = round(dominant["count"] / total * 100, 1)
                obs.append(
                    f"**{name}** is a binary outcome column. "
                    f"**{dominant['value']}** accounts for {dom_pct}% of records "
                    f"({dominant['count']:,} of {total:,}). "
                    f"Class imbalance may affect rate calculations."
                )
        priority = "high"

    elif unique == 1:
        obs.append(f"**{name}** has only one unique value — no discriminatory power.")
        priority = "low"
    elif unique <= 5:
        cats = ", ".join(str(v) for v in sample[:unique])
        obs.append(
            f"**{name}** has {unique} categories ({cats}) — "
            f"ideal for segmentation and group comparison."
        )
        priority = "high"
    elif unique <= 20:
        obs.append(
            f"**{name}** has {unique} distinct values — suitable for bar charts and grouping."
        )
        priority = "medium"
    else:
        obs.append(
            f"**{name}** has high cardinality ({unique} unique values). "
            f"Consider top-N filtering before visualising."
        )
        priority = "low"

    if null_pct > 10:
        obs.append(
            f"**{null_pct}%** of records are missing **{name}** — review data quality."
        )
        priority = "high"

    if not obs:
        return None

    return {
        "title":           f"{name} — Category Structure",
        "insight_text":    " ".join(obs),
        "category":        "distribution",
        "priority":        priority,
        "evidence_fields": [name],
        "confidence":      0.85,
    }


def _insight_for_metric(col: dict[str, Any], total_rows: int) -> dict[str, Any] | None:
    name     = col["name"]
    null_pct = col["null_percentage"]
    hint     = col.get("semantic_hint", "none")

    obs:      list[str] = []
    priority: str       = "medium"

    # use stored stats if available (from schema_profiler improvements)
    mn  = col.get("min")
    mx  = col.get("max")
    avg = col.get("mean")
    std = col.get("std")
    skw = col.get("skew")

    if mn is not None and mx is not None and avg is not None:
        prefix = "💰 " if hint == "currency" else ""
        obs.append(
            f"{prefix}**{name}** ranges {mn:,.2f}–{mx:,.2f}, "
            f"avg={avg:,.2f}"
            + (f", std={std:,.2f}" if std is not None else "")
            + "."
        )
        if mx > 0 and (mx - mn) / mx > 0.5:
            obs.append(
                f"Wide spread ({mx - mn:,.2f}) suggests significant variation or outliers."
            )
            priority = "high"
        if skw is not None and abs(skw) > 1.0:
            direction = "right" if skw > 0 else "left"
            obs.append(f"Distribution is {direction}-skewed (skew={skw:.2f}).")

    if null_pct > 5:
        obs.append(
            f"{null_pct}% of **{name}** values are missing — imputation may be needed."
        )
        priority = "high"

    if col["unique_count"] <= 5:
        obs.append(
            f"**{name}** has only {col['unique_count']} distinct values — "
            f"may behave like a categorical variable."
        )

    if not obs:
        obs.append(
            f"**{name}** is a numeric metric with {col['unique_count']:,} unique values."
        )

    return {
        "title":           f"{name} — Metric Profile",
        "insight_text":    " ".join(obs),
        "category":        "descriptive",
        "priority":        priority,
        "evidence_fields": [name],
        "confidence":      0.80,
    }


def _insight_for_date(col: dict[str, Any], total_rows: int) -> dict[str, Any] | None:
    name     = col["name"]
    unique   = col["unique_count"]
    null_pct = col["null_percentage"]
    sample   = col.get("sample_values", [])

    obs: list[str] = []
    if unique > 1:
        rng = f" (sample range: {sample[0]} → {sample[-1]})" if len(sample) >= 2 else ""
        obs.append(
            f"**{name}** spans {unique} unique time points{rng} — "
            f"enables trend and seasonality analysis."
        )
    else:
        obs.append(f"**{name}** has only {unique} date value — limited temporal analysis.")

    if null_pct > 0:
        obs.append(f"{null_pct}% of **{name}** values are missing.")

    return {
        "title":           f"{name} — Temporal Coverage",
        "insight_text":    " ".join(obs),
        "category":        "trend",
        "priority":        "high" if unique > 5 else "medium",
        "evidence_fields": [name],
        "confidence":      0.88,
    }


# ── cross-column insights ─────────────────────────────────────────

def _cross_column_insights(schema_profile: dict[str, Any]) -> list[dict[str, Any]]:
    columns    = schema_profile.get("columns", [])
    summary    = schema_profile.get("dataset_summary", {})
    total_rows = summary.get("rows", 0)

    insights: list[dict[str, Any]] = []

    metrics    = [c for c in columns if c["role"] == "metric"]
    dimensions = [c for c in columns if c["role"] == "dimension"
                  and c.get("semantic_hint") != "likely_id"]
    dates      = [c for c in columns if c["role"] == "date"]
    targets    = [c for c in columns if c.get("semantic_hint") == "likely_target"]

    high_null = [c["name"] for c in columns if c["null_percentage"] > 15]
    if high_null:
        insights.append({
            "title": "⚠ Data Quality Warning",
            "insight_text": (
                f"{len(high_null)} column(s) have >15% missing values: "
                f"**{', '.join(high_null)}**. "
                f"Bias may affect analysis."
            ),
            "category": "data_quality",
            "priority": "high",
            "evidence_fields": high_null,
            "confidence": 0.95,
        })

    if metrics and dimensions:
        insights.append({
            "title": "Analytical Potential",
            "insight_text": (
                f"{len(metrics)} metric(s) × {len(dimensions)} dimension(s) — "
                f"supports segmented analysis and cross-group comparisons."
            ),
            "category": "structural",
            "priority": "medium",
            "evidence_fields": [c["name"] for c in metrics[:3] + dimensions[:3]],
            "confidence": 0.90,
        })

    if targets:
        target_names = ", ".join(f"**{t['name']}**" for t in targets)
        insights.append({
            "title": "Target Variable Detected",
            "insight_text": (
                f"Binary outcome column(s) found: {target_names}. "
                f"These are suitable for conversion rate, churn rate, or classification analysis."
            ),
            "category": "structural",
            "priority": "high",
            "evidence_fields": [t["name"] for t in targets],
            "confidence": 0.92,
        })

    if dates:
        insights.append({
            "title": "Time-Series Capability",
            "insight_text": (
                f"Date/time field(s): **{', '.join(d['name'] for d in dates)}**. "
                f"Trend and seasonality analysis is available."
            ),
            "category": "trend",
            "priority": "high",
            "evidence_fields": [d["name"] for d in dates],
            "confidence": 0.92,
        })

    if total_rows < 100:
        insights.append({
            "title": "Small Dataset",
            "insight_text": (
                f"Only {total_rows} rows — treat results as exploratory, not conclusive."
            ),
            "category": "data_quality",
            "priority": "medium",
            "evidence_fields": [],
            "confidence": 0.95,
        })
    elif total_rows > 100_000:
        insights.append({
            "title": "Large Dataset",
            "insight_text": (
                f"{total_rows:,} rows — aggregated views are recommended for readability."
            ),
            "category": "structural",
            "priority": "low",
            "evidence_fields": [],
            "confidence": 0.90,
        })

    return insights


# ── executive summary ─────────────────────────────────────────────

def _build_executive_summary(
    schema_profile: dict[str, Any],
    intent:         dict[str, Any],
) -> list[str]:
    summary    = schema_profile.get("dataset_summary", {})
    columns    = schema_profile.get("columns", [])
    total_rows = summary.get("rows", 0)
    total_cols = summary.get("columns", 0)

    metrics    = [c for c in columns if c["role"] == "metric"]
    dimensions = [c for c in columns if c["role"] == "dimension"
                  and c.get("semantic_hint") != "likely_id"]
    dates      = [c for c in columns if c["role"] == "date"]
    targets    = [c for c in columns if c.get("semantic_hint") == "likely_target"]
    high_null  = [c for c in columns if c["null_percentage"] > 10]

    bullets: list[str] = []
    goal = intent.get("business_goal", intent.get("raw_prompt", "BI exploration"))

    bullets.append(
        f"Dataset: **{total_rows:,} records** × **{total_cols} fields**. "
        f"Analysed for: {goal}."
    )

    if dimensions:
        bullets.append(
            f"**{len(dimensions)} dimension(s)** available for segmentation: "
            + ", ".join(f"**{d['name']}**" for d in dimensions[:4]) + "."
        )

    if metrics:
        bullets.append(
            f"**{len(metrics)} numeric metric(s)** for aggregation: "
            + ", ".join(f"**{m['name']}**" for m in metrics[:4]) + "."
        )

    if targets:
        bullets.append(
            f"**Target column(s) detected**: "
            + ", ".join(f"**{t['name']}**" for t in targets)
            + " — suitable for rate/conversion analysis."
        )

    if dates:
        bullets.append(
            f"**Temporal fields**: "
            + ", ".join(f"**{d['name']}**" for d in dates)
            + " — trend analysis available."
        )

    if high_null:
        bullets.append(
            f"⚠ **Data quality**: {len(high_null)} field(s) with >10% missing values — "
            + ", ".join(f"**{c['name']}**" for c in high_null[:3]) + "."
        )
    else:
        bullets.append("✓ **Data completeness**: No significant missing values detected.")

    return bullets[:5]


# ── public API ────────────────────────────────────────────────────

def generate_dataset_insights(
    schema_profile: dict[str, Any],
    intent:         dict[str, Any],
) -> dict[str, Any]:
    """
    Generate dataset-level structural + quality insights.
    Does NOT generate insights from query results (that's insight_narration_agent).
    """
    columns    = schema_profile.get("columns", [])
    total_rows = schema_profile.get("dataset_summary", {}).get("rows", 0)

    per_col: list[dict[str, Any]] = []
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
            per_col.append(ins)

    cross   = _cross_column_insights(schema_profile)
    all_ins = per_col + cross

    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_ins.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 3))

    return {
        "executive_summary": _build_executive_summary(schema_profile, intent),
        "insights":          all_ins[:8],
    }


# backward-compatible alias
def generate_insights(
    intent:         dict[str, Any],
    charts:         list[dict[str, Any]],
    schema_profile: dict[str, Any],
) -> dict[str, Any]:
    result = generate_dataset_insights(schema_profile, intent)
    result["key_takeaways"] = []   # removed but keeping key for compat
    return result