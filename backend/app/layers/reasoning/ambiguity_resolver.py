"""
app/layers/reasoning/ambiguity_resolver.py
══════════════════════════════════════════════════════════════════════
Ambiguity Resolver — NEW component.

Detects when a user query is too ambiguous to safely plan an analysis,
and returns a structured clarification request instead of guessing.

This prevents the silent failure mode where:
  - Query: "show me the rate"   (which rate? of what? grouped by what?)
  - System guesses and produces a random chart
  - User gets confused

Design:
  - Fully deterministic (no LLM required)
  - Returns AmbiguitySignal(is_ambiguous, reason, clarification_options)
  - Dashboard orchestrator checks this BEFORE planning
  - If ambiguous, returns HTTP 200 with needs_clarification=True
    so the frontend can render a follow-up prompt
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.models import MetricType, QueryIntent, QuestionType


@dataclass
class AmbiguitySignal:
    is_ambiguous:          bool
    reason:                str                = ""
    clarification_question: str               = ""
    options:               list[str]          = field(default_factory=list)
    partial_intent:        Optional[dict[str, Any]] = None


_GENERIC_PROMPTS = frozenset({
    "show me", "give me", "what is", "tell me", "analyse", "analyze",
    "dashboard", "overview", "report", "data", "everything", "all",
})

_MIN_QUERY_TOKENS = 4


def check_for_ambiguity(
    prompt:         str,
    intent:         QueryIntent,
    schema_profile: dict[str, Any],
) -> AmbiguitySignal:
    """
    Inspect the parsed intent and determine if it is too ambiguous to proceed.

    Returns an AmbiguitySignal. If is_ambiguous=True, the orchestrator
    should return a clarification request to the frontend instead of executing.
    """
    tokens = prompt.lower().split()

    # ── 1. Extremely short / generic prompt ──────────────────────
    if len(tokens) < _MIN_QUERY_TOKENS:
        generic_overlap = sum(1 for t in tokens if t in _GENERIC_PROMPTS)
        if generic_overlap >= len(tokens) - 1:
            return AmbiguitySignal(
                is_ambiguous=True,
                reason="Query is too generic to determine a specific analysis.",
                clarification_question="What would you like to analyse?",
                options=_suggest_analyses(schema_profile),
            )

    # ── 2. Rate query with no target column ──────────────────────
    if intent.metric == MetricType.rate and intent.target_variable is None:
        metrics = [c for c in schema_profile.get("columns", [])
                   if c["role"] in ("metric", "dimension") and c.get("unique_count", 0) == 2]
        if not metrics:
            return AmbiguitySignal(
                is_ambiguous=True,
                reason="Rate/conversion metric requested but no binary outcome column found.",
                clarification_question=(
                    "Which column represents the outcome you want to measure the rate of?"
                ),
                options=[c["name"] for c in schema_profile.get("columns", [])
                         if c["role"] == "dimension"][:6],
                partial_intent=intent.dict(),
            )

    # ── 3. Trend query with no date column ───────────────────────
    if intent.question_type == QuestionType.trend and intent.time_column is None:
        dates = [c for c in schema_profile.get("columns", []) if c["role"] == "date"]
        if not dates:
            return AmbiguitySignal(
                is_ambiguous=True,
                reason="Trend analysis requested but no date/time column found.",
                clarification_question=(
                    "Which column represents time for the trend analysis?"
                ),
                options=[c["name"] for c in schema_profile.get("columns", [])
                         if c["role"] in ("metric", "dimension")][:6],
                partial_intent=intent.dict(),
            )

    # ── 4. Comparison with no clear dimension ────────────────────
    if (
        intent.question_type == QuestionType.comparison
        and intent.primary_dimension is None
    ):
        dims = [c for c in schema_profile.get("columns", []) if c["role"] == "dimension"]
        if dims:
            return AmbiguitySignal(
                is_ambiguous=True,
                reason="Comparison requested but no grouping dimension specified.",
                clarification_question=(
                    "What would you like to compare across? Select a grouping column:"
                ),
                options=[c["name"] for c in dims[:6]],
                partial_intent=intent.dict(),
            )

    # ── 5. Multi-metric ambiguity ─────────────────────────────────
    metrics = [c for c in schema_profile.get("columns", []) if c["role"] == "metric"]
    if (
        intent.metric in (MetricType.sum, MetricType.mean)
        and intent.target_variable is None
        and len(metrics) > 3
    ):
        return AmbiguitySignal(
            is_ambiguous=True,
            reason=f"Multiple numeric columns found but no specific metric mentioned.",
            clarification_question=(
                f"Which numeric value would you like to compute the "
                f"{intent.metric} of?"
            ),
            options=[c["name"] for c in metrics[:6]],
            partial_intent=intent.dict(),
        )

    return AmbiguitySignal(is_ambiguous=False)


def _suggest_analyses(schema_profile: dict[str, Any]) -> list[str]:
    """Generate contextual suggested analyses based on schema."""
    cols = schema_profile.get("columns", [])
    suggestions: list[str] = []

    dims     = [c for c in cols if c["role"] == "dimension"
                and c.get("semantic_hint") not in ("likely_id", "high_cardinality")]
    metrics  = [c for c in cols if c["role"] == "metric"]
    dates    = [c for c in cols if c["role"] == "date"]
    targets  = [c for c in cols if c.get("semantic_hint") == "likely_target"]

    if targets and dims:
        suggestions.append(
            f"Conversion rate of '{targets[0]['name']}' by '{dims[0]['name']}'"
        )
    if dates and metrics:
        suggestions.append(
            f"Trend of '{metrics[0]['name']}' over time"
        )
    if dims:
        suggestions.append(f"Distribution of '{dims[0]['name']}'")
    if metrics and dims:
        suggestions.append(
            f"Average '{metrics[0]['name']}' by '{dims[0]['name']}'"
        )
    if dims and len(dims) > 1:
        suggestions.append(f"Compare '{dims[0]['name']}' vs '{dims[1]['name']}'")

    return suggestions[:5] if suggestions else ["Show me an overview of this dataset"]
