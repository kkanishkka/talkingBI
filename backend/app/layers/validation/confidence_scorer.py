"""
app/layers/validation/confidence_scorer.py
══════════════════════════════════════════════════════════════════════
Confidence Scoring System — NEW component.

Problem solved:
  The original system had a single quality_score on ValidationReport
  computed as: 1.0 - issues*0.4 - warnings*0.08
  This was too simple — it mixed data quality issues with plan quality.

This module provides multi-factor confidence scoring:

  Factors:
    1. Data quality score    — null rates, row count, skew
    2. Plan confidence       — from AnalysisPlan.confidence (LLM or rule-based)
    3. Result quality score  — cardinality, value variance, row count
    4. Schema match score    — how well the query fields exist in schema
    5. Inference source penalty — LLM > rule-based > default

  Output: ConfidenceReport
    overall_confidence: float  (0.0 – 1.0)
    factors:            dict   (per-factor breakdown)
    tier:               str    ("high", "medium", "low", "unreliable")
    user_message:       str    (shown in AssumptionBlock)
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.models import AnalysisPlan, ExecutionResult, QueryIntent


@dataclass
class ConfidenceReport:
    overall_confidence: float
    tier:               str               # "high" | "medium" | "low" | "unreliable"
    factors:            dict[str, float]  = field(default_factory=dict)
    user_message:       str               = ""

    @classmethod
    def unreliable(cls, reason: str) -> "ConfidenceReport":
        return cls(
            overall_confidence=0.0,
            tier="unreliable",
            factors={},
            user_message=f"Cannot assess confidence: {reason}",
        )


def compute_confidence(
    intent:         QueryIntent,
    plan:           AnalysisPlan,
    result:         ExecutionResult,
    schema_profile: dict[str, Any],
) -> ConfidenceReport:
    """
    Compute a multi-factor confidence score for the current analysis.
    All factors are in [0, 1]. Overall is a weighted average.
    """
    if not result.success or not result.data:
        return ConfidenceReport.unreliable("Execution failed or returned no data.")

    factors: dict[str, float] = {}

    # ── Factor 1: Data quality ────────────────────────────────────
    factors["data_quality"] = _data_quality_score(intent, schema_profile)

    # ── Factor 2: Plan confidence ─────────────────────────────────
    factors["plan_confidence"] = float(plan.confidence)

    # ── Factor 3: Result quality ──────────────────────────────────
    factors["result_quality"] = _result_quality_score(result)

    # ── Factor 4: Schema field match ─────────────────────────────
    factors["schema_match"] = _schema_match_score(intent, schema_profile)

    # ── Factor 5: Inference source ────────────────────────────────
    # LLM-sourced intents are penalised slightly less than pure rule-based
    # (because LLM handles nuance better, but may hallucinate)
    # In practice both return the same weight here — adjustable.
    factors["inference_source"] = 0.85  # neutral weight for now

    # ── Weighted overall ──────────────────────────────────────────
    weights = {
        "data_quality":     0.25,
        "plan_confidence":  0.30,
        "result_quality":   0.25,
        "schema_match":     0.15,
        "inference_source": 0.05,
    }
    overall = sum(factors[k] * weights[k] for k in weights)
    overall = round(min(1.0, max(0.0, overall)), 3)

    tier = _tier(overall)
    message = _user_message(tier, factors)

    return ConfidenceReport(
        overall_confidence=overall,
        tier=tier,
        factors=factors,
        user_message=message,
    )


# ── Factor scorers ────────────────────────────────────────────────

def _data_quality_score(intent: QueryIntent, schema_profile: dict[str, Any]) -> float:
    """Score based on null rates and row count of relevant columns."""
    columns = schema_profile.get("columns", [])
    relevant_names: set[str] = set(filter(None, [
        intent.primary_dimension,
        intent.secondary_dimension,
        intent.target_variable,
        intent.time_column,
    ]))

    if not relevant_names:
        return 0.75  # can't assess — give benefit of doubt

    relevant_cols = [c for c in columns if c["name"] in relevant_names]
    if not relevant_cols:
        return 0.50  # columns not found in schema

    avg_null = sum(c.get("null_percentage", 0) for c in relevant_cols) / len(relevant_cols)
    null_penalty = min(1.0, avg_null / 50.0)   # 50% nulls → full penalty

    row_count = schema_profile.get("dataset_summary", {}).get("rows", 0)
    size_score = 1.0 if row_count >= 1000 else max(0.3, row_count / 1000)

    return round((1.0 - null_penalty) * 0.6 + size_score * 0.4, 3)


def _result_quality_score(result: ExecutionResult) -> float:
    """Score based on result cardinality, variance, and completeness."""
    if result.row_count == 0:
        return 0.0
    if result.row_count == 1:
        return 0.40   # single row — degenerate result

    # Extract numeric values
    y = result.y_field
    vals: list[float] = []
    for row in result.data:
        try:
            vals.append(float(row[y]))
        except (KeyError, TypeError, ValueError):
            pass

    if not vals:
        return 0.30   # no numeric values

    # Variance check — all same value is useless
    value_set = set(round(v, 6) for v in vals)
    if len(value_set) == 1:
        return 0.35   # zero variance

    # Row count score (sweet spot: 3–30 rows for readability)
    if 3 <= result.row_count <= 30:
        cardinality_score = 1.0
    elif result.row_count <= 2:
        cardinality_score = 0.50
    elif result.row_count <= 50:
        cardinality_score = 0.85
    else:
        cardinality_score = 0.70  # too many rows — hard to interpret

    return round(min(1.0, cardinality_score), 3)


def _schema_match_score(intent: QueryIntent, schema_profile: dict[str, Any]) -> float:
    """Score based on how many intent fields were found in the schema."""
    column_names = {
        c["name"].lower()
        for c in schema_profile.get("columns", [])
    }

    requested = [f for f in [
        intent.primary_dimension,
        intent.secondary_dimension,
        intent.target_variable,
        intent.time_column,
    ] if f is not None]

    if not requested:
        return 0.75  # no explicit fields — trust fallback selection

    matched = sum(1 for f in requested if f.lower() in column_names)
    return round(matched / len(requested), 3)


# ── Tier classification ───────────────────────────────────────────

def _tier(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.60:
        return "medium"
    if score >= 0.40:
        return "low"
    return "unreliable"


def _user_message(tier: str, factors: dict[str, float]) -> str:
    messages = {
        "high":       "Analysis confidence is high — results are reliable.",
        "medium":     "Analysis confidence is moderate — treat results as indicative.",
        "low":        "Analysis confidence is low — verify assumptions before acting.",
        "unreliable": "Results may be unreliable — check data quality and query clarity.",
    }
    msg = messages.get(tier, "")
    # Append specific low-factor hints
    low_factors = [k for k, v in factors.items() if v < 0.50]
    if low_factors:
        factor_names = {
            "data_quality":    "data quality",
            "plan_confidence": "analysis plan",
            "result_quality":  "result shape",
            "schema_match":    "column matching",
        }
        hints = [factor_names.get(f, f) for f in low_factors]
        msg += f" Low confidence in: {', '.join(hints)}."
    return msg
