"""
app/pipeline/context.py
══════════════════════════════════════════════════════════════════════
PipelineContext — shared state object passed through every pipeline step.

Design principles:
  - Single mutable object that flows through all steps
  - Each step reads inputs it needs and writes its outputs
  - Orchestrator assembles final response from context at the end
  - Simplifies testing: mock context → test any step in isolation
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import pandas as pd

from app.core.models import (
    AnalysisPlan, AssumptionBlock, ExecutionResult,
    KPICoverage, QueryIntent, SchemaContext, ValidationReport, VizSpec,
)
from app.core.session_store import SessionContext
from app.layers.validation.confidence_scorer import ConfidenceReport
from app.layers.reasoning.ambiguity_resolver import AmbiguitySignal


class PipelineContext:
    """
    Mutable container for all intermediate pipeline artifacts.
    Created per-request by the orchestrator.
    """

    def __init__(self, prompt: str, session_id: str) -> None:
        self.request_id:    str = str(uuid.uuid4())[:8]
        self.prompt:        str = prompt
        self.session_id:    str = session_id
        self.started_at:    float = time.time()

        # populated by ingestion layer
        self.df:            Optional[pd.DataFrame] = None
        self.filename:      str = ""
        self.ingestion_warnings: list[str] = []

        # populated by semantic layer
        self.schema_profile:  Optional[dict[str, Any]] = None
        self.schema_context:  Optional[SchemaContext]  = None

        # populated by session store
        self.session_ctx:   Optional[SessionContext] = None

        # populated by reasoning layer
        self.ambiguity_signal: Optional[AmbiguitySignal] = None
        self.intent:           Optional[QueryIntent]     = None
        self.plan:             Optional[AnalysisPlan]    = None
        self.result:           Optional[ExecutionResult] = None
        self.validation:       Optional[ValidationReport] = None
        self.refinement_log:   list[str] = []

        # populated by validation layer
        self.confidence:    Optional[ConfidenceReport] = None

        # populated by presentation layer
        self.primary_viz:     Optional[dict[str, Any]] = None
        self.overview_charts: list[dict[str, Any]]     = []
        self.all_vizs:        list[dict[str, Any]]     = []
        self.assumption_block: Optional[AssumptionBlock] = None
        self.kpi_coverage:    Optional[dict[str, Any]]  = None
        self.layouts:         list[dict[str, Any]]      = []
        self.insight_report:  dict[str, Any]            = {}
        self.dataset_output:  dict[str, Any]            = {}

        # accumulated warnings
        self.warnings: list[str] = []

    @property
    def elapsed(self) -> float:
        return round(time.time() - self.started_at, 2)

    def add_warning(self, msg: str) -> None:
        if msg and msg not in self.warnings:
            self.warnings.append(msg)

    def add_warnings(self, msgs: list[str]) -> None:
        for msg in msgs:
            self.add_warning(msg)
