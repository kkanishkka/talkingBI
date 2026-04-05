"""
app/core/models.py
══════════════════════════════════════════════════════════════════════
Single source of truth for all Pydantic data contracts.

Every agent input/output, every API request/response, and every
intermediate result uses a type defined here.

Design rules:
  - No Optional[X] without a sensible default
  - Every list field defaults to []
  - Every "source" field tracks whether LLM or rules produced the value
  - Every assumption is explicit, never silent
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── enumerations ──────────────────────────────────────────────────

class QuestionType(str, Enum):
    ranking      = "ranking"
    comparison   = "comparison"
    trend        = "trend"
    distribution = "distribution"
    aggregation  = "aggregation"
    correlation  = "correlation"
    filtered_lookup = "filtered_lookup"
    overview     = "overview"


class MetricType(str, Enum):
    rate    = "rate"
    count   = "count"
    sum     = "sum"
    mean    = "mean"
    median  = "median"
    max     = "max"
    min     = "min"
    ratio   = "ratio"
    percent_change = "percent_change"


class ColumnRole(str, Enum):
    metric    = "metric"
    dimension = "dimension"
    date      = "date"
    id        = "id"
    target    = "target"   # binary outcome / flag column
    text      = "text"


class SemanticHint(str, Enum):
    likely_target    = "likely_target"    # binary yes/no outcome
    likely_id        = "likely_id"        # identifier, skip for analysis
    currency         = "currency"         # financial amount
    percentage       = "percentage"       # already a ratio 0–100
    count_field      = "count_field"      # integer counts
    score            = "score"            # rating or score
    category_key     = "category_key"     # clean categorical
    high_cardinality = "high_cardinality" # too many values for chart
    none             = "none"


class InferenceSource(str, Enum):
    llm        = "llm"
    rule_based = "rule_based"
    default    = "default"


class ChartType(str, Enum):
    bar            = "bar"
    horizontal_bar = "horizontal_bar"
    line           = "line"
    pie            = "pie"
    donut          = "donut"
    histogram      = "histogram"
    kpi_card       = "kpi_card"
    scatter        = "scatter"
    area           = "area"


class InsightCategory(str, Enum):
    descriptive  = "descriptive"
    diagnostic   = "diagnostic"
    prescriptive = "prescriptive"
    evaluative   = "evaluative"
    data_quality = "data_quality"
    structural   = "structural"
    trend        = "trend"
    distribution = "distribution"


class Priority(str, Enum):
    high   = "high"
    medium = "medium"
    low    = "low"


# ── column-level models ───────────────────────────────────────────

class ColumnProfile(BaseModel):
    name:           str
    dtype:          str
    role:           ColumnRole
    semantic_hint:  SemanticHint = SemanticHint.none
    null_count:     int          = 0
    null_percentage: float       = 0.0
    unique_count:   int          = 0
    sample_values:  list[Any]    = Field(default_factory=list)
    top_values:     list[dict[str, Any]] = Field(default_factory=list)
    # metric-only stats
    min:    Optional[float] = None
    max:    Optional[float] = None
    mean:   Optional[float] = None
    median: Optional[float] = None
    std:    Optional[float] = None
    skew:   Optional[float] = None


class SchemaContext(BaseModel):
    """Full enriched schema — output of the schema + semantic layer."""
    rows:    int
    columns: int
    column_names: list[str] = Field(default_factory=list)
    column_profiles: list[ColumnProfile] = Field(default_factory=list)

    # convenience accessors (computed, not stored)
    def metrics(self)    -> list[ColumnProfile]:
        return [c for c in self.column_profiles if c.role == ColumnRole.metric]
    def dimensions(self) -> list[ColumnProfile]:
        return [c for c in self.column_profiles if c.role == ColumnRole.dimension]
    def dates(self)      -> list[ColumnProfile]:
        return [c for c in self.column_profiles if c.role == ColumnRole.date]
    def targets(self)    -> list[ColumnProfile]:
        return [c for c in self.column_profiles
                if c.semantic_hint == SemanticHint.likely_target]
    def find(self, name: str) -> Optional[ColumnProfile]:
        for c in self.column_profiles:
            if c.name == name:
                return c
        return None


# ── intent models ─────────────────────────────────────────────────

class FilterSpec(BaseModel):
    column:   str
    operator: str  # ==, !=, >, <, >=, <=, in, not_in
    value:    Any



class QueryIntent(BaseModel):
    """Output of QueryUnderstandingAgent."""
    question_type:       QuestionType      = QuestionType.overview
    metric:              MetricType        = MetricType.count
    primary_dimension:   Optional[str]     = None
    secondary_dimension: Optional[str]     = None
    target_variable:     Optional[str]     = None
    rate_value:          Optional[str]     = None   # positive class for rate
    color_schema:        Optional[str]     = None   # requested color/theme
    filters:             list[FilterSpec]  = Field(default_factory=list)
    time_column:         Optional[str]     = None
    time_grain:          Optional[str]     = None   # D, W, M, Q, Y
    sort_direction:      str               = "desc"
    top_n:               Optional[int]     = None
    requested_kpis:      list[str]         = Field(default_factory=list)
    raw_prompt:          str               = ""
    assumptions:         list[str]         = Field(default_factory=list)
    _source:             InferenceSource   = InferenceSource.rule_based

    class Config:
        use_enum_values = True


# ── plan models ───────────────────────────────────────────────────

class PlanOperation(BaseModel):
    step:   int
    op:     str   # filter | groupby_agg | value_counts | sort | top_n | time_resample
    args:   dict[str, Any] = Field(default_factory=dict)


class AnalysisPlan(BaseModel):
    """Output of AnalysisPlanBuilder."""
    operations:    list[PlanOperation] = Field(default_factory=list)
    result_columns: list[str]          = Field(default_factory=list)
    x_field:       str                 = ""
    y_field:       str                 = "value"
    metric_label:  str                 = "Value"
    result_label:  str                 = "Analysis Result"
    formula_spec:  str                 = ""   # human-readable formula
    confidence:    float               = 0.80
    reasoning:     str                 = ""
    _source:       InferenceSource     = InferenceSource.rule_based


# ── execution models ──────────────────────────────────────────────

class ExecutionResult(BaseModel):
    success:              bool
    data:                 list[dict[str, Any]] = Field(default_factory=list)
    x_field:              str                  = ""
    y_field:              str                  = "value"
    row_count:            int                  = 0
    metric_label:         str                  = "Value"
    result_label:         str                  = "Analysis Result"
    intermediate_counts:  dict[str, int]       = Field(default_factory=dict)
    error:                Optional[str]        = None
    sample_warning:       Optional[str]        = None  # set when df was sampled


class ValidationReport(BaseModel):
    valid:          bool
    issues:         list[str]              = Field(default_factory=list)
    warnings:       list[str]             = Field(default_factory=list)
    corrections:    list[str]             = Field(default_factory=list)
    quality_score:  float                 = 1.0
    is_retryable:   bool                  = False
    retry_suggestion: Optional[dict[str, Any]] = None


# ── visualization models ──────────────────────────────────────────

class VizSpec(BaseModel):
    """Frontend-consumable chart specification."""
    chart_type:     ChartType
    title:          str
    x_field:        str                  = ""
    y_field:        str                  = "value"
    label_field:    Optional[str]        = None   # pie/donut
    value_field:    Optional[str]        = None   # pie/donut
    data:           list[dict[str, Any]] = Field(default_factory=list)
    annotations:    list[str]            = Field(default_factory=list)
    y_format:       str                  = "number"   # number | percent | currency
    y_axis_label:   str                  = ""
    color_scheme:   str                  = "default"
    why_this_chart: str                  = ""
    confidence:     float                = 0.85
    is_primary:     bool                 = False
    formula_spec:   str                  = ""

    class Config:
        use_enum_values = True


class LayoutCell(BaseModel):
    viz_index:  int     # index into visualizations list
    col_start:  int     # 1-based CSS grid col-start
    col_span:   int     # CSS grid col-span (out of 12)
    row_span:   int     = 1


class DashboardLayout(BaseModel):
    layout_id:   str
    layout_name: str
    description: str
    cells:       list[LayoutCell] = Field(default_factory=list)


# ── insight models ────────────────────────────────────────────────

class InsightItem(BaseModel):
    title:           str
    insight_text:    str
    category:        InsightCategory = InsightCategory.descriptive
    priority:        Priority        = Priority.medium
    evidence_fields: list[str]       = Field(default_factory=list)
    confidence:      float           = 0.80

    class Config:
        use_enum_values = True


class InsightReport(BaseModel):
    """Output of InsightNarrationAgent — query-specific."""
    headline:     str               = ""
    bullets:      list[str]         = Field(default_factory=list)
    so_what:      str               = ""
    data_caveat:  Optional[str]     = None
    _source:      InferenceSource   = InferenceSource.rule_based


class KPICoverage(BaseModel):
    requested_kpis:    list[str] = Field(default_factory=list)
    covered_kpis:      list[str] = Field(default_factory=list)
    uncovered_kpis:    list[str] = Field(default_factory=list)
    coverage_pct:      float     = 0.0
    coverage_note:     str       = ""


# ── session model ─────────────────────────────────────────────────

class SessionContext(BaseModel):
    session_id:        str
    schema_context:    Optional[SchemaContext]  = None
    previous_intent:   Optional[QueryIntent]    = None
    previous_result:   Optional[ExecutionResult] = None
    conversation:      list[str]               = Field(default_factory=list)
    created_at:        float                   = 0.0
    last_accessed:     float                   = 0.0


# ── API response model ────────────────────────────────────────────

class AssumptionBlock(BaseModel):
    """Transparent listing of every inference the system made."""
    metric_assumption:    str = ""   # e.g. "Rate computed as proportion where y='yes'"
    dimension_assumption: str = ""   # e.g. "Grouped by 'job' as requested"
    filter_assumptions:   list[str] = Field(default_factory=list)
    formula_spec:         str = ""   # e.g. "mean(y='yes') GROUP BY job ORDER BY rate DESC"
    positive_class:       Optional[str] = None
    can_correct:          bool = True  # tells UI to show "Correct me" affordance


class DashboardResponse(BaseModel):
    """The single response shape from POST /dashboard."""
    message:           str

    # query-specific primary output
    analysis_report: dict[str, Any]  = Field(default_factory=dict)
    assumptions:     AssumptionBlock = Field(default_factory=AssumptionBlock)
    kpi_coverage:    KPICoverage     = Field(default_factory=KPICoverage)

    # charts + layouts
    visualizations:  list[dict[str, Any]] = Field(default_factory=list)  # VizSpec dicts
    layouts:         list[dict[str, Any]] = Field(default_factory=list)   # DashboardLayout dicts

    # dataset-level context
    executive_summary: list[str]          = Field(default_factory=list)
    dataset_insights:  list[dict[str, Any]] = Field(default_factory=list)
    dataset_profile: dict[str, Any]        = Field(default_factory=dict)

    # meta
    session_id:      Optional[str]        = None
    warnings:        list[str]            = Field(default_factory=list)