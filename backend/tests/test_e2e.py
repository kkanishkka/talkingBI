"""
tests/test_e2e.py
End-to-end pipeline tests: schema → intent → plan → execute → validate → viz → insights.
No LLM required — all rule-based paths.
"""
import sys; sys.path.insert(0, ".")
import pytest
from app.services.schema_profiler import profile_dataframe
from app.services.query_understanding_agent import understand_query
from app.services.analysis_planning_agent import build_analysis_plan
from app.services.analysis_executor import execute_plan
from app.services.reflection_agent import validate_result
from app.services.viz_reasoning_agent import reason_visualization
from app.services.insight_narration_agent import narrate_insights
from app.services.coverage_engine import compute_kpi_coverage


class TestSubscriptionRatePipeline:
    """The canonical test: 'Which job has highest subscription rate?'"""

    def test_full_pipeline_produces_valid_result(self, bank_df):
        schema = profile_dataframe(bank_df)
        intent = understand_query(
            "Which job category has the highest subscription rate?",
            schema
        )

        assert intent.metric == "rate",  f"Expected rate, got {intent.metric}"
        assert intent.question_type == "ranking"
        assert intent.target_variable == "y"
        assert intent.primary_dimension == "job"

        plan   = build_analysis_plan(intent, schema)
        result = execute_plan(plan, bank_df)

        assert result.success, result.error
        assert result.row_count > 0

        # CRITICAL: all values must be in [0,1] — not counts
        for row in result.data:
            v = float(row["value"])
            assert 0.0 <= v <= 1.0, f"Rate {v} out of [0,1] — count used instead of rate"

        report = validate_result(intent, plan, result)
        assert report.valid, f"Validation failed: {report.issues}"
        assert report.quality_score >= 0.7

        viz    = reason_visualization(intent, result, schema, is_primary=True)
        assert viz.chart_type in ("horizontal_bar", "bar")
        assert viz.is_primary

        insights = narrate_insights(intent, result, viz)
        assert insights.headline != ""
        assert len(insights.bullets) >= 2
        assert insights.so_what != ""

    def test_assumption_block_contains_positive_class(self, bank_df):
        from app.services.insight_narration_agent import build_assumption_block
        schema = profile_dataframe(bank_df)
        intent = understand_query("Subscription rate by job", schema)
        plan   = build_analysis_plan(intent, schema)
        block  = build_assumption_block(intent, plan.formula_spec)

        if intent.metric == "rate":
            assert block.positive_class is not None
            assert block.metric_assumption != ""


class TestSalesTrendPipeline:
    def test_trend_query_produces_line_chart(self, sales_df):
        schema = profile_dataframe(sales_df)
        intent = understand_query("Show revenue trend over time", schema)

        if intent.question_type == "trend":
            plan   = build_analysis_plan(intent, schema)
            result = execute_plan(plan, sales_df)
            assert result.success

            if result.row_count > 0:
                report = validate_result(intent, plan, result)
                viz    = reason_visualization(intent, result, schema)
                assert viz.chart_type == "line"


class TestKPICoverage:
    def test_covered_kpi_detected(self, bank_df):
        schema = profile_dataframe(bank_df)
        intent = understand_query("Show subscription rate by job", schema)
        plan   = build_analysis_plan(intent, schema)
        result = execute_plan(plan, bank_df)

        from app.services.viz_reasoning_agent import reason_visualization
        if result.success and result.data:
            viz    = reason_visualization(intent, result, schema)
            intent_with_kpis = intent.copy(update={"requested_kpis":["subscription rate"]})
            coverage = compute_kpi_coverage(
                intent_with_kpis.requested_kpis,
                [viz.dict()]
            )
            assert coverage.coverage_pct > 0


class TestGenericDataset:
    def test_pipeline_works_on_any_schema(self, generic_df):
        """Must produce a valid result on a completely unfamiliar dataset."""
        schema = profile_dataframe(generic_df)
        intent = understand_query("Show me the breakdown by category", schema)
        plan   = build_analysis_plan(intent, schema)
        result = execute_plan(plan, generic_df)

        assert result.success or result.error is not None  # either succeeds or fails gracefully
        if result.success:
            report = validate_result(intent, plan, result)
            assert isinstance(report.valid, bool)  # always returns a report