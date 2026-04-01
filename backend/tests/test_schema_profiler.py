"""
tests/test_schema_profiler.py
Tests for schema_profiler and semantic_classifier correctness.
"""
import pandas as pd
import pytest
import sys; sys.path.insert(0, ".")

from app.services.schema_profiler import profile_dataframe


class TestRoleInference:
    def test_numeric_column_is_metric(self):
        df = pd.DataFrame({"revenue": [100, 200, 300]})
        p  = profile_dataframe(df)
        col = p["columns"][0]
        assert col["role"] == "metric"

    def test_string_column_is_dimension(self):
        df = pd.DataFrame({"job": ["admin", "tech", "student"]})
        p  = profile_dataframe(df)
        assert p["columns"][0]["role"] == "dimension"

    def test_plain_month_column_is_not_date(self):
        """Regression: month=1,2,3 should NOT be classified as date."""
        df = pd.DataFrame({"month": [1, 2, 3, 4, 5]})
        p  = profile_dataframe(df)
        assert p["columns"][0]["role"] != "date", \
            "Plain 'month' integer column must not be classified as date"

    def test_pdays_is_not_date(self):
        df = pd.DataFrame({"pdays": [-1, 0, 30, 60, 90]})
        p  = profile_dataframe(df)
        assert p["columns"][0]["role"] != "date"

    def test_actual_date_column_is_date(self):
        df = pd.DataFrame({"order_date": ["2024-01-01","2024-02-01","2024-03-01"]})
        p  = profile_dataframe(df)
        assert p["columns"][0]["role"] == "date"

    def test_low_cardinality_numeric_is_dimension(self):
        """A numeric col with 2 unique values across 1000 rows should be dimension."""
        df = pd.DataFrame({"flag": [0]*700 + [1]*300})
        p  = profile_dataframe(df)
        assert p["columns"][0]["role"] == "dimension"

    def test_id_column_is_dimension_not_metric(self):
        df = pd.DataFrame({"customer_id": [1, 2, 3, 4, 5]})
        p  = profile_dataframe(df)
        # should be dimension (not metric) because of _id suffix
        assert p["columns"][0]["role"] == "dimension"


class TestSemanticHints:
    def test_binary_yn_column_is_likely_target(self, bank_df, bank_schema):
        y_col = next(c for c in bank_schema["columns"] if c["name"] == "y")
        assert y_col["semantic_hint"] == "likely_target", \
            f"'y' column should be likely_target, got {y_col['semantic_hint']}"

    def test_balance_is_currency(self, bank_df, bank_schema):
        bal = next(c for c in bank_schema["columns"] if c["name"] == "balance")
        assert bal["semantic_hint"] == "currency", \
            f"'balance' should be currency hint, got {bal['semantic_hint']}"

    def test_job_is_category_key(self, bank_df, bank_schema):
        job = next(c for c in bank_schema["columns"] if c["name"] == "job")
        assert job["semantic_hint"] == "category_key"

    def test_metric_stats_present(self, bank_df, bank_schema):
        bal = next(c for c in bank_schema["columns"] if c["name"] == "balance")
        assert "min" in bal and "max" in bal and "mean" in bal

    def test_no_datetime_warning(self, bank_df):
        """Profiling must not raise a pandas datetime FutureWarning."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                profile_dataframe(bank_df)
            except FutureWarning as e:
                pytest.fail(f"FutureWarning raised: {e}")