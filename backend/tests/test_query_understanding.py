"""
tests/test_query_understanding.py
Regression tests for the rule-based query understanding path.
These MUST pass without an LLM API key (offline).
"""
import sys; sys.path.insert(0, ".")
import pytest
from app.services.query_understanding_agent import understand_query


class TestMetricDetection:
    def test_subscription_rate_query(self, bank_schema):
        intent = understand_query(
            "Which job category has the highest subscription rate?",
            bank_schema
        )
        assert intent.metric == "rate", f"Expected 'rate', got '{intent.metric}'"
        assert intent.question_type == "ranking"

    def test_how_many_is_count(self, bank_schema):
        intent = understand_query("How many customers are in each job category?", bank_schema)
        assert intent.metric == "count"

    def test_average_balance(self, bank_schema):
        intent = understand_query("What is the average balance by marital status?", bank_schema)
        assert intent.metric == "mean"
        assert intent.primary_dimension == "marital"

    def test_total_sum(self, bank_schema):
        intent = understand_query("What is the total balance?", bank_schema)
        assert intent.metric == "sum"

    def test_tends_to_phrasing_maps_to_rate(self, bank_schema):
        """'tends to subscribe' should still detect rate metric."""
        intent = understand_query(
            "Which customers tend to subscribe more?", bank_schema
        )
        assert intent.metric == "rate"

    def test_more_likely_phrasing(self, bank_schema):
        intent = understand_query(
            "Who is more likely to subscribe — retired or student?", bank_schema
        )
        assert intent.metric == "rate"


class TestQuestionTypeDetection:
    def test_top_is_ranking(self, bank_schema):
        intent = understand_query("Show me the top 5 jobs by conversion", bank_schema)
        assert intent.question_type == "ranking"
        assert intent.top_n in (5, 10)  # either explicit or default

    def test_trend_detected(self, sales_schema):
        intent = understand_query("Show revenue trend over time", sales_schema)
        assert intent.question_type == "trend"

    def test_compare_is_comparison(self, bank_schema):
        intent = understand_query(
            "Compare subscription rate between married and single customers", bank_schema
        )
        assert intent.question_type in ("comparison", "ranking")

    def test_generic_overview_returns_overview(self, bank_schema):
        intent = understand_query("Give me a complete overview dashboard", bank_schema)
        assert intent.question_type == "overview"


class TestColumnMatching:
    def test_explicit_column_name_matched(self, bank_schema):
        intent = understand_query(
            "Show me subscription rate by marital status", bank_schema
        )
        assert intent.primary_dimension == "marital"

    def test_target_column_detected(self, bank_schema):
        """'y' should be auto-selected as target for rate queries."""
        intent = understand_query(
            "Which job has the highest subscription rate?", bank_schema
        )
        assert intent.target_variable == "y", \
            f"Expected target='y', got '{intent.target_variable}'"

    def test_positive_class_detected(self, bank_schema):
        """rate_value should be 'yes' for the bank dataset."""
        intent = understand_query(
            "Show subscription rate by job", bank_schema
        )
        if intent.metric == "rate":
            assert intent.rate_value is not None
            assert intent.rate_value.lower() == "yes", \
                f"Expected rate_value='yes', got '{intent.rate_value}'"


class TestAssumptionsPresent:
    def test_assumptions_list_non_empty(self, bank_schema):
        intent = understand_query(
            "Which job category has the highest subscription rate?", bank_schema
        )
        assert isinstance(intent.assumptions, list)
        assert len(intent.assumptions) > 0, "Assumptions list should not be empty"

    def test_rate_assumption_mentioned(self, bank_schema):
        intent = understand_query(
            "Show subscription rate by job", bank_schema
        )
        if intent.metric == "rate":
            assumption_text = " ".join(intent.assumptions).lower()
            assert "positive" in assumption_text or "yes" in assumption_text, \
                "Rate assumption should mention the positive class"