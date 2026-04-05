"""
app/services/semantic_classifier.py
══════════════════════════════════════════════════════════════════════
Assigns a SemanticHint to each column beyond the basic role (metric/
dimension/date) already set by schema_profiler.

This is the layer that turns:
  "y" → likely_target  (binary outcome column)
  "balance" → currency
  "age" → score
  "customer_id" → likely_id
  "job" → category_key

Rules are deterministic and run first. LLM confirmation is optional
for genuinely ambiguous columns.

Used by:
  - schema_profiler (enriches ColumnProfile.semantic_hint)
  - query_understanding_agent (picks better target/metric defaults)
  - analysis_planning_agent (uses rate_value from likely_target)
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
from typing import Any

from app.core.models import ColumnRole, SemanticHint


# ── name-pattern matchers ─────────────────────────────────────────

_ID_PATTERNS = re.compile(
    r"^(id|.*_id|.*_key|.*_code|rownum|index|pk|uuid|guid)$", re.I
)

_TARGET_NAMES = frozenset({
    "y", "target", "label", "outcome", "subscribed", "converted",
    "churn", "churned", "default", "fraud", "clicked", "purchased",
    "responded", "approved", "success", "result", "flag", "status",
    "is_churn", "is_fraud", "is_converted", "is_subscribed",
})

_CURRENCY_PATTERNS = re.compile(
    r"(revenue|sales|amount|balance|price|cost|spend|budget|income"
    r"|profit|loss|earnings|salary|wage|fee|payment|transaction)", re.I
)

_PERCENTAGE_PATTERNS = re.compile(
    r"(rate|ratio|percent|pct|proportion|share|fraction)", re.I
)

_COUNT_PATTERNS = re.compile(
    r"(count|num_|n_|number_of|qty|quantity|total_|cnt)", re.I
)

_SCORE_PATTERNS = re.compile(
    r"(score|rating|rank|grade|index|level|tier|age|duration|days|months"
    r"|years|tenure|seniority|weight|height|temperature)", re.I
)

_HIGH_CARDINALITY_THRESHOLD = 100


def classify_column(
    name:         str,
    role:         ColumnRole,
    dtype:        str,
    unique_count: int,
    total_rows:   int,
    sample_values: list[Any],
    top_values:   list[dict[str, Any]],
) -> SemanticHint:
    """
    Assign a SemanticHint to a single column.
    Returns SemanticHint.none if nothing specific is detected.
    """
    col_lower = name.lower().strip()

    # ── 1. Identifier detection ───────────────────────────────────
    if _ID_PATTERNS.match(col_lower):
        return SemanticHint.likely_id

    # High uniqueness ratio for object columns → likely identifier
    if (
        total_rows > 0
        and unique_count / total_rows > 0.95
        and role in (ColumnRole.dimension, ColumnRole.metric)
    ):
        return SemanticHint.likely_id

    # ── 2. Target / outcome detection ────────────────────────────
    if col_lower in _TARGET_NAMES:
        return SemanticHint.likely_target

    # Binary column (2 unique values) that looks like yes/no
    if unique_count == 2 and role in (ColumnRole.dimension, ColumnRole.metric):
        sv_lower = {str(v).lower() for v in sample_values if v is not None}
        binary_sets = [
            {"yes", "no"},
            {"true", "false"},
            {"0", "1"},
            {"0.0", "1.0"},
            {"1", "2"},
            {"y", "n"},
            {"success", "failure"},
            {"pass", "fail"},
        ]
        for bset in binary_sets:
            if sv_lower <= bset or bset <= sv_lower:
                return SemanticHint.likely_target

    # ── 3. Currency / financial metric ───────────────────────────
    if role == ColumnRole.metric and _CURRENCY_PATTERNS.search(col_lower):
        return SemanticHint.currency

    # ── 4. Percentage / ratio ─────────────────────────────────────
    if role == ColumnRole.metric and _PERCENTAGE_PATTERNS.search(col_lower):
        # Confirm values are in 0–100 or 0–1 range
        numeric_vals = []
        for v in sample_values:
            try:
                numeric_vals.append(float(v))
            except (TypeError, ValueError):
                pass
        if numeric_vals:
            if max(numeric_vals) <= 1.01:
                return SemanticHint.percentage
            if max(numeric_vals) <= 100.0:
                return SemanticHint.percentage

    # ── 5. Count fields ───────────────────────────────────────────
    if role == ColumnRole.metric and _COUNT_PATTERNS.search(col_lower):
        return SemanticHint.count_field

    # ── 6. Score / rating ─────────────────────────────────────────
    if role == ColumnRole.metric and _SCORE_PATTERNS.search(col_lower):
        return SemanticHint.score

    # ── 7. High cardinality dimension ─────────────────────────────
    if role == ColumnRole.dimension and unique_count > _HIGH_CARDINALITY_THRESHOLD:
        return SemanticHint.high_cardinality

    # ── 8. Clean category key ─────────────────────────────────────
    if role == ColumnRole.dimension and 2 <= unique_count <= 30:
        return SemanticHint.category_key

    return SemanticHint.none


def classify_all_columns(
    columns:    list[dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    """
    Enrich a list of column profile dicts with semantic_hint.
    Input/output are plain dicts (compatible with both old and new code).
    """
    enriched = []
    for col in columns:
        hint = classify_column(
            name=         col["name"],
            role=         ColumnRole(col["role"]),
            dtype=        col.get("dtype", "object"),
            unique_count= col.get("unique_count", 0),
            total_rows=   total_rows,
            sample_values= col.get("sample_values", []),
            top_values=   col.get("top_values", []),
        )
        enriched.append({**col, "semantic_hint": hint.value})
    return enriched


def find_best_target(columns: list[dict[str, Any]]) -> str | None:
    """
    Return the most likely target/outcome column name.
    Priority: likely_target hint > binary dimension column name match.
    """
    # Pass 1: explicit target hint
    for col in columns:
        if col.get("semantic_hint") == SemanticHint.likely_target.value:
            return col["name"]
    # Pass 2: binary dimension (fallback)
    for col in columns:
        if col.get("role") == ColumnRole.dimension.value and col.get("unique_count") == 2:
            return col["name"]
    return None


def find_best_dimension(
    columns: list[dict[str, Any]],
    exclude: list[str] | None = None,
) -> str | None:
    """
    Return the most analytically interesting dimension.
    Prefers category_key hint, low-to-medium cardinality.
    """
    exclude = exclude or []
    candidates = [
        c for c in columns
        if c.get("role") == ColumnRole.dimension.value
        and c["name"] not in exclude
        and c.get("semantic_hint") not in (
            SemanticHint.likely_id.value,
            SemanticHint.likely_target.value,
            SemanticHint.high_cardinality.value,
        )
    ]
    # Sort by cardinality: prefer 3–15 unique values
    candidates.sort(key=lambda c: abs(c.get("unique_count", 0) - 8))
    return candidates[0]["name"] if candidates else None


def find_best_metric(
    columns: list[dict[str, Any]],
    exclude: list[str] | None = None,
) -> str | None:
    """Return the most analytically useful metric column."""
    exclude = exclude or []
    priority = [SemanticHint.currency.value, SemanticHint.count_field.value,
                SemanticHint.score.value, SemanticHint.none.value]
    for hint in priority:
        for col in columns:
            if (col.get("role") == ColumnRole.metric.value
                    and col["name"] not in exclude
                    and col.get("semantic_hint") == hint
                    and col.get("dtype", "object") not in ("object", "string", "category")):
                return col["name"]
    return None