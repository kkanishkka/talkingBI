"""
tests/test_executor.py
Tests for analysis_executor — correctness of rate, count, multi-groupby, sort.
"""
import pandas as pd
import pytest
import sys; sys.path.insert(0, ".")

from app.core.models import AnalysisPlan, PlanOperation
from app.services.analysis_executor import execute_plan


def make_plan(ops, x="category", y="value", metric_label="Value", result_label="Test"):
    return AnalysisPlan(
        operations=     [PlanOperation(**o) for o in ops],
        result_columns= [x, y],
        x_field=        x,
        y_field=        y,
        metric_label=   metric_label,
        result_label=   result_label,
        formula_spec=   "test formula",
    )


class TestRateComputation:
    def test_rate_is_proportion_not_count(self, bank_df):
        """Rate must be in [0,1], NOT a raw count."""
        plan = make_plan([
            {"step":1, "op":"groupby_agg", "args":{
                "group_by":["job"], "target":"y",
                "agg_fn":"rate", "rate_value":"yes"
            }},
            {"step":2, "op":"sort", "args":{"by":"value","ascending":False}},
        ], x="job", metric_label="Subscription Rate")

        result = execute_plan(plan, bank_df)
        assert result.success, result.error
        assert result.row_count > 0

        for row in result.data:
            v = float(row["value"])
            assert 0.0 <= v <= 1.0, \
                f"Rate value {v} is out of [0,1] — count was used instead of rate"

    def test_rate_retired_higher_than_bluecollar(self, bank_df):
        """Retired should have higher subscription rate than blue-collar in our fixture."""
        plan = make_plan([
            {"step":1, "op":"groupby_agg", "args":{
                "group_by":["job"], "target":"y",
                "agg_fn":"rate", "rate_value":"yes"
            }},
        ], x="job")

        result = execute_plan(plan, bank_df)
        rows = {r["job"]: float(r["value"]) for r in result.data}
        assert rows.get("retired", 0) > rows.get("blue-collar", 0), \
            f"retired rate {rows.get('retired')} should > blue-collar {rows.get('blue-collar')}"

    def test_rate_case_insensitive_positive_class(self):
        """rate_value matching must be case-insensitive."""
        df = pd.DataFrame({
            "group": ["A","A","B","B"],
            "outcome": ["Yes","No","YES","no"],
        })
        plan = make_plan([
            {"step":1, "op":"groupby_agg", "args":{
                "group_by":["group"], "target":"outcome",
                "agg_fn":"rate", "rate_value":"yes"
            }},
        ], x="group")
        result = execute_plan(plan, df)
        assert result.success
        rates = {r["group"]: float(r["value"]) for r in result.data}
        assert rates["A"] == pytest.approx(0.5, abs=0.01)
        assert rates["B"] == pytest.approx(0.5, abs=0.01)


class TestCountComputation:
    def test_count_sums_to_total_rows(self, bank_df):
        plan = make_plan([
            {"step":1, "op":"groupby_agg", "args":{
                "group_by":["job"], "target":"job", "agg_fn":"count"
            }},
        ], x="job")
        result = execute_plan(plan, bank_df)
        assert result.success
        total = sum(int(r["value"]) for r in result.data)
        assert total == len(bank_df)

    def test_value_counts_sums_to_total(self, bank_df):
        plan = make_plan([
            {"step":1, "op":"value_counts", "args":{"column":"marital","normalize":False}},
        ], x="marital")
        result = execute_plan(plan, bank_df)
        assert result.success
        assert sum(int(r["value"]) for r in result.data) == len(bank_df)


class TestMultiGroupBy:
    def test_two_dimension_groupby(self, bank_df):
        plan = make_plan([
            {"step":1, "op":"groupby_agg", "args":{
                "group_by":["job","marital"], "target":"y",
                "agg_fn":"rate", "rate_value":"yes"
            }},
        ], x="job")
        result = execute_plan(plan, bank_df)
        assert result.success
        # multi-groupby should produce more rows than single groupby
        assert result.row_count > 0


class TestSortAndTopN:
    def test_sort_descending(self, bank_df):
        plan = make_plan([
            {"step":1, "op":"groupby_agg", "args":{
                "group_by":["job"], "target":"job", "agg_fn":"count"
            }},
            {"step":2, "op":"sort", "args":{"by":"value","ascending":False}},
        ], x="job")
        result = execute_plan(plan, bank_df)
        vals = [float(r["value"]) for r in result.data]
        assert vals == sorted(vals, reverse=True)

    def test_top_n_limits_rows(self, bank_df):
        plan = make_plan([
            {"step":1, "op":"groupby_agg", "args":{
                "group_by":["job"], "target":"job", "agg_fn":"count"
            }},
            {"step":2, "op":"sort",  "args":{"by":"value","ascending":False}},
            {"step":3, "op":"top_n", "args":{"n":3}},
        ], x="job")
        result = execute_plan(plan, bank_df)
        assert result.row_count == 3


class TestTimeResample:
    def test_time_resample_produces_rows(self, sales_df):
        plan = make_plan([
            {"step":1, "op":"time_resample", "args":{
                "date_col":"order_date","freq":"M","target":"revenue","agg_fn":"sum"
            }},
        ], x="order_date")
        result = execute_plan(plan, sales_df)
        assert result.success
        assert result.row_count > 0

    def test_time_resample_no_warning(self, sales_df):
        import warnings
        plan = make_plan([
            {"step":1, "op":"time_resample", "args":{
                "date_col":"order_date","freq":"M","target":"revenue","agg_fn":"sum"
            }},
        ], x="order_date")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                execute_plan(plan, sales_df)
            except FutureWarning as e:
                pytest.fail(f"FutureWarning from time_resample: {e}")


class TestRowLimit:
    def test_large_df_is_sampled(self):
        import numpy as np
        big_df = pd.DataFrame({
            "cat": np.random.choice(["A","B","C"], size=600_000),
            "val": np.random.randn(600_000),
        })
        plan = make_plan([
            {"step":1,"op":"groupby_agg","args":{"group_by":["cat"],"target":"val","agg_fn":"mean"}},
        ], x="cat")
        result = execute_plan(plan, big_df)
        assert result.success
        assert result.sample_warning is not None, "Should have sample_warning for 600k row df"