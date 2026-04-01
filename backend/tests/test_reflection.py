"""
tests/test_reflection.py
Tests that ReflectionAgent correctly detects common failure modes.
"""
import sys; sys.path.insert(0, ".")
import pytest
from app.core.models import (
    AnalysisPlan, ExecutionResult, MetricType,
    PlanOperation, QueryIntent, QuestionType,
)
from app.services.reflection_agent import validate_result


def make_intent(metric="rate", qtype="ranking", dim="job", target="y", rate_val="yes"):
    return QueryIntent(
        question_type=     qtype,
        metric=            metric,
        primary_dimension= dim,
        target_variable=   target,
        rate_value=        rate_val,
        raw_prompt=        "test",
    )


def make_plan(ops=None):
    ops = ops or [PlanOperation(step=1, op="groupby_agg",
                                args={"group_by":["job"],"target":"y","agg_fn":"rate","rate_value":"yes"})]
    return AnalysisPlan(operations=ops, x_field="job", y_field="value",
                        result_label="Test", metric_label="Rate", formula_spec="test")


def make_result(data, success=True, error=None):
    return ExecutionResult(
        success=success, data=data, x_field="job", y_field="value",
        row_count=len(data), metric_label="Rate", result_label="Test",
        intermediate_counts={"input": 1000}, error=error,
    )


class TestRateRangeCheck:
    def test_rate_greater_than_1_is_invalid(self):
        """Rate values > 1.0 mean count was used instead of rate."""
        result = make_result([
            {"job":"retired","value":250},
            {"job":"student","value":180},
        ])
        intent = make_intent(metric="rate")
        report = validate_result(intent, make_plan(), result)
        assert not report.valid
        assert report.is_retryable
        assert any("1.0" in i or "rate" in i.lower() for i in report.issues)

    def test_correct_rate_is_valid(self):
        result = make_result([
            {"job":"retired","value":0.251},
            {"job":"student","value":0.228},
            {"job":"management","value":0.131},
        ])
        intent = make_intent(metric="rate")
        report = validate_result(intent, make_plan(), result)
        assert report.valid
        assert not report.issues


class TestEmptyResult:
    def test_empty_data_is_invalid(self):
        result = make_result([])
        report = validate_result(make_intent(), make_plan(), result)
        assert not report.valid
        assert report.is_retryable

    def test_execution_failure_is_invalid(self):
        result = make_result([], success=False, error="column not found")
        result.success = False
        result.error   = "column not found"
        report = validate_result(make_intent(), make_plan(), result)
        assert not report.valid
        assert any("execution failed" in i.lower() for i in report.issues)


class TestQualityScore:
    def test_clean_result_has_high_quality(self):
        data = [{"job":f"cat{i}","value":0.1*i} for i in range(1,6)]
        result = make_result(data)
        report = validate_result(make_intent(), make_plan(), result)
        assert report.quality_score >= 0.8

    def test_single_row_reduces_quality(self):
        result = make_result([{"job":"only","value":0.5}])
        report = validate_result(make_intent(), make_plan(), result)
        # single row should warn and reduce quality
        assert report.quality_score < 1.0
        assert len(report.warnings) > 0


class TestRetrySignal:
    def test_rate_gt_1_provides_retry_suggestion(self):
        result = make_result([{"job":"A","value":250},{"job":"B","value":100}])
        report = validate_result(make_intent(metric="rate"), make_plan(), result)
        assert report.is_retryable
        assert report.retry_suggestion is not None
        assert "change_metric" in report.retry_suggestion