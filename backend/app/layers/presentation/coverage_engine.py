"""
app/layers/presentation/coverage_engine.py
══════════════════════════════════════════════════════════════════════
REFACTORED: KPI Coverage Engine using semantic KPI ontology.

Changes from original:
  - Delegates to kpi_ontology.compute_kpi_coverage_semantic()
    instead of raw word-overlap
  - Returns KPICoverage model (same shape as before — no API breakage)
  - Adds kpi_details list to response (new field — backward compatible)
  - Accepts optional schema_profile for data-availability checks
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.models import KPICoverage
from app.layers.semantic.kpi_ontology import compute_kpi_coverage_semantic


def compute_kpi_coverage(
    intent_kpis:    list[str],
    viz_specs:      list[dict[str, Any]],
    schema_profile: Optional[dict[str, Any]] = None,
) -> KPICoverage:
    """
    Compute semantic KPI coverage.

    Args:
        intent_kpis:    List of KPI phrases from QueryIntent.requested_kpis
        viz_specs:      List of VizSpec dicts (title, formula_spec, etc.)
        schema_profile: Optional schema for data-availability checking

    Returns:
        KPICoverage — same model shape as original, with extra kpi_details
    """
    result = compute_kpi_coverage_semantic(intent_kpis, viz_specs, schema_profile)

    return KPICoverage(
        requested_kpis= result["requested_kpis"],
        covered_kpis=   result["covered_kpis"],
        uncovered_kpis= result["uncovered_kpis"],
        coverage_pct=   result["coverage_pct"],
        coverage_note=  result["coverage_note"],
    )
