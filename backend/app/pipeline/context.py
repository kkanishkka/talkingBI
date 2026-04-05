"""
app/pipeline/context.py — v2 (multi-chart fields added)

New attributes vs v1:
  dashboard_plan   DashboardPlan  — output of planner.plan_dashboard()
  multi_result     MultiExecutionResult — output of multi_executor
  result_insights  list[dict]     — output of result_insight_engine

All existing attributes preserved unchanged.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import pandas as pd

# forward-ref friendly imports
from app.core.models import (
    AnalysisPlan, AssumptionBlock, ExecutionResult,
    KPICoverage, QueryIntent, SchemaContext, ValidationReport,
)


class PipelineContext:
    """Mutable scratchpad passed through every pipeline step."""

    def __init__(self, prompt: str, session_id: str) -> None:
        self.request_id: str = str(uuid.uuid4())[:8]
        self.prompt:     str = prompt
        self.session_id: str = session_id
        self._start:     float = time.time()

        # ingestion
        self.df:       Optional[pd.DataFrame]  = None
        self.filename: Optional[str]            = None

        # profiling
        self.schema_profile: Optional[dict]        = None
        self.schema_context: Optional[SchemaContext] = None

        # session
        self.session_ctx: Any = None

        # understanding
        self.intent:           Optional[QueryIntent]    = None
        self.ambiguity_signal: Any                      = None

        # single-plan (backward-compat, used for validation)
        self.plan:       Optional[AnalysisPlan]     = None
        self.result:     Optional[ExecutionResult]  = None
        self.validation: Optional[ValidationReport] = None
        self.refinement_log: list[str] = []

        # ── NEW: multi-chart plan & results ───────────────────────
        self.dashboard_plan:  Any = None   # DashboardPlan
        self.multi_result:    Any = None   # MultiExecutionResult
        self.result_insights: list[dict] = []

        # scoring
        self.confidence: Any = None

        # presentation
        self.primary_viz:   Optional[dict] = None
        self.all_vizs:      list[dict]     = []
        self.overview_charts: list[dict]   = []
        self.is_kpi_only:   bool           = False
        self.layouts:       list[dict]     = []

        # narration
        self.insight_report:   Optional[dict] = None
        self.assumption_block: Optional[AssumptionBlock] = None
        self.kpi_coverage:     Optional[dict] = None

        # dataset insights
        self.dataset_output: dict = {}

        # warnings
        self.warnings: list[str] = []

    @property
    def elapsed(self) -> float:
        return round(time.time() - self._start, 2)

    def add_warning(self, msg: str) -> None:
        if msg:
            self.warnings.append(msg)

    def add_warnings(self, msgs: list[str]) -> None:
        for m in msgs:
            self.add_warning(m)