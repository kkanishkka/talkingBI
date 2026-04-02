"""
app/layers/semantic/kpi_ontology.py
══════════════════════════════════════════════════════════════════════
KPI Ontology — semantic registry of business KPIs.

Problem solved:
  The original coverage_engine did pure keyword overlap:
    "subscription rate" ∩ chart_title_words → covered/not covered
  This breaks for synonyms ("conversion rate" vs "subscription rate")
  and produces false positives ("rate" matching unrelated charts).

This module provides:
  1. KPIDefinition — structured definition of each KPI
  2. KPI_REGISTRY — extensible list of known business KPIs
  3. resolve_kpi_phrases() — maps user phrases to canonical KPIs
  4. match_kpi_to_vizspecs() — semantic coverage matching

Design:
  - Fully deterministic (no LLM)
  - Extensible: add new KPIs by appending to KPI_REGISTRY
  - Dataset-agnostic: uses column roles + semantic hints, not column names
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class KPIDefinition:
    """
    A canonical KPI definition.

    name:           Canonical name ("Conversion Rate")
    aliases:        Synonyms and alternate phrasings
    metric_type:    The underlying metric ("rate", "count", "sum", "mean", etc.)
    requires_target: Whether this KPI needs a binary target column (for rate KPIs)
    requires_date:   Whether this KPI requires a date column (for trend KPIs)
    formula_hint:   Human-readable formula displayed in assumption block
    category:       Business domain ("marketing", "finance", "operations", etc.)
    """
    name:            str
    aliases:         list[str]          = field(default_factory=list)
    metric_type:     str                = "count"
    requires_target: bool               = False
    requires_date:   bool               = False
    formula_hint:    str                = ""
    category:        str                = "general"

    def matches_phrase(self, phrase: str) -> bool:
        """Return True if phrase matches this KPI's name or any alias."""
        low = phrase.lower().strip()
        if low in self.name.lower():
            return True
        return any(low in alias.lower() or alias.lower() in low
                   for alias in self.aliases)

    def is_covered_by_viz(self, viz: dict[str, Any]) -> bool:
        """
        Check whether a VizSpec dict covers this KPI.
        Uses title, formula_spec, and chart_type — not just word overlap.
        """
        text = (
            viz.get("title", "") + " " +
            viz.get("formula_spec", "") + " " +
            viz.get("y_axis_label", "")
        ).lower()

        # metric type must match
        if self.metric_type == "rate" and "rate" not in text and "%" not in text:
            return False
        if self.metric_type == "sum" and not any(
            w in text for w in ["total", "sum", "revenue", "sales"]
        ):
            return False

        # at least one alias keyword must appear
        name_words = set(re.findall(r"\w+", self.name.lower()))
        alias_words: set[str] = set()
        for alias in self.aliases:
            alias_words.update(re.findall(r"\w+", alias.lower()))

        all_keywords = name_words | alias_words
        # exclude stop words
        stop = {"the", "a", "an", "of", "by", "per", "for", "and", "or", "rate", "total"}
        significant = {w for w in all_keywords if len(w) > 3 and w not in stop}

        return any(kw in text for kw in significant)


# ── KPI Registry ──────────────────────────────────────────────────
# Add new KPIs here. Grouped by business domain.

KPI_REGISTRY: list[KPIDefinition] = [

    # ── Marketing / Conversion ────────────────────────────────────
    KPIDefinition(
        name="Conversion Rate",
        aliases=["conversion", "subscribe rate", "subscription rate",
                 "sign-up rate", "opt-in rate", "response rate",
                 "success rate", "hit rate"],
        metric_type="rate",
        requires_target=True,
        formula_hint="Proportion of records where outcome = positive class",
        category="marketing",
    ),
    KPIDefinition(
        name="Churn Rate",
        aliases=["churn", "attrition", "dropout rate", "cancellation rate",
                 "customer loss"],
        metric_type="rate",
        requires_target=True,
        formula_hint="Proportion of customers who left in the period",
        category="marketing",
    ),
    KPIDefinition(
        name="Click-Through Rate",
        aliases=["ctr", "click rate", "open rate"],
        metric_type="rate",
        requires_target=True,
        formula_hint="Clicks / Impressions",
        category="marketing",
    ),

    # ── Revenue / Finance ─────────────────────────────────────────
    KPIDefinition(
        name="Total Revenue",
        aliases=["revenue", "total sales", "gross revenue", "income",
                 "total income", "earnings"],
        metric_type="sum",
        formula_hint="SUM(revenue column)",
        category="finance",
    ),
    KPIDefinition(
        name="Average Revenue Per User",
        aliases=["arpu", "average revenue", "revenue per customer",
                 "avg revenue", "mean revenue"],
        metric_type="mean",
        formula_hint="MEAN(revenue column) GROUP BY customer",
        category="finance",
    ),
    KPIDefinition(
        name="Average Order Value",
        aliases=["aov", "average order", "mean order value",
                 "average transaction", "avg transaction"],
        metric_type="mean",
        formula_hint="MEAN(order_value column)",
        category="finance",
    ),
    KPIDefinition(
        name="Profit Margin",
        aliases=["margin", "profit rate", "net margin", "gross margin"],
        metric_type="mean",
        formula_hint="MEAN(profit / revenue)",
        category="finance",
    ),

    # ── Operations ────────────────────────────────────────────────
    KPIDefinition(
        name="Volume / Count",
        aliases=["count", "total count", "number of", "how many",
                 "transaction count", "order count"],
        metric_type="count",
        formula_hint="COUNT(*)",
        category="operations",
    ),
    KPIDefinition(
        name="Average Duration",
        aliases=["avg duration", "mean duration", "average time",
                 "average age", "mean age", "average tenure"],
        metric_type="mean",
        formula_hint="MEAN(duration column)",
        category="operations",
    ),
    KPIDefinition(
        name="Growth Rate",
        aliases=["growth", "month over month", "yoy", "year over year",
                 "quarterly growth", "trend", "change over time"],
        metric_type="percent_change",
        requires_date=True,
        formula_hint="(current_period - prior_period) / prior_period",
        category="operations",
    ),

    # ── Risk ──────────────────────────────────────────────────────
    KPIDefinition(
        name="Default Rate",
        aliases=["default", "bad debt rate", "fraud rate", "risk rate"],
        metric_type="rate",
        requires_target=True,
        formula_hint="Proportion of records flagged as default/fraud",
        category="risk",
    ),
]


# ── Resolver functions ────────────────────────────────────────────

def resolve_kpi_phrases(phrases: list[str]) -> list[KPIDefinition]:
    """
    Map a list of user KPI phrases to canonical KPIDefinitions.
    Unrecognised phrases return a generic KPIDefinition for display purposes.
    """
    resolved: list[KPIDefinition] = []
    for phrase in phrases:
        matched = next(
            (kpi for kpi in KPI_REGISTRY if kpi.matches_phrase(phrase)),
            None,
        )
        if matched:
            resolved.append(matched)
        else:
            # Generic fallback — keeps the phrase visible without crashing
            resolved.append(KPIDefinition(
                name=phrase.title(),
                aliases=[phrase.lower()],
                metric_type="count",
                formula_hint=f"Custom KPI: {phrase}",
                category="custom",
            ))
    return resolved


def compute_kpi_coverage_semantic(
    requested_phrases: list[str],
    viz_specs:         list[dict[str, Any]],
    schema_profile:    Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Semantic KPI coverage computation.

    Returns a dict matching the KPICoverage model shape:
        requested_kpis, covered_kpis, uncovered_kpis,
        coverage_pct, coverage_note, kpi_details (new)
    """
    if not requested_phrases:
        return {
            "requested_kpis": [],
            "covered_kpis":   [],
            "uncovered_kpis": [],
            "coverage_pct":   100.0,
            "coverage_note":  "No specific KPIs requested — full overview generated.",
            "kpi_details":    [],
        }

    kpi_defs = resolve_kpi_phrases(requested_phrases)
    covered:   list[str] = []
    uncovered: list[str] = []
    kpi_details: list[dict[str, Any]] = []

    for kpi_def, phrase in zip(kpi_defs, requested_phrases):
        is_covered = any(kpi_def.is_covered_by_viz(viz) for viz in viz_specs)

        # Additional check: if KPI requires a target and none in schema → flag
        needs_data = ""
        if not is_covered and schema_profile and kpi_def.requires_target:
            targets = [
                c for c in schema_profile.get("columns", [])
                if c.get("semantic_hint") == "likely_target"
            ]
            if not targets:
                needs_data = f"No binary target column found in dataset for '{phrase}'"

        if is_covered:
            covered.append(phrase)
        else:
            uncovered.append(phrase)

        kpi_details.append({
            "phrase":          phrase,
            "canonical_name":  kpi_def.name,
            "category":        kpi_def.category,
            "formula_hint":    kpi_def.formula_hint,
            "covered":         is_covered,
            "needs_data_note": needs_data,
        })

    total  = len(requested_phrases)
    pct    = round(len(covered) / total * 100, 1) if total > 0 else 100.0

    if pct == 100.0:
        note = "All requested KPIs are covered."
    elif pct >= 75.0:
        note = f"Most KPIs covered ({pct}%). Missing: {', '.join(uncovered)}."
    else:
        note = (
            f"Only {pct}% of KPIs covered. "
            f"Missing: {', '.join(uncovered)}. "
            f"Try a more specific query for each uncovered KPI."
        )

    return {
        "requested_kpis": requested_phrases,
        "covered_kpis":   covered,
        "uncovered_kpis": uncovered,
        "coverage_pct":   pct,
        "coverage_note":  note,
        "kpi_details":    kpi_details,
    }
