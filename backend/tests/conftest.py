"""
tests/conftest.py
Shared pytest fixtures used across all test modules.
"""
import pandas as pd
import pytest


@pytest.fixture
def bank_df():
    """Simplified bank marketing dataset — classic subscription rate problem."""
    return pd.DataFrame({
        "age":     [25, 45, 35, 60, 28, 55, 38, 22, 48, 33],
        "job":     ["student","management","blue-collar","retired","student",
                    "retired","management","student","blue-collar","technician"],
        "marital": ["single","married","married","divorced","single",
                    "married","married","single","married","single"],
        "balance": [100, 5000, 1200, 8000, 50, 12000, 3400, 200, 900, 600],
        "y":       ["no","yes","no","yes","yes","yes","no","yes","no","no"],
    })


@pytest.fixture
def sales_df():
    """Simple sales dataset with dates, revenue, regions."""
    return pd.DataFrame({
        "order_date": ["2024-01","2024-01","2024-02","2024-02","2024-03","2024-03"],
        "region":     ["North","South","North","South","North","South"],
        "product":    ["A","B","A","A","B","B"],
        "revenue":    [1200, 800, 1500, 1100, 900, 1300],
        "units":      [10, 8, 12, 9, 7, 11],
    })


@pytest.fixture
def generic_df():
    """Minimal generic dataset to test dataset-agnostic behaviour."""
    return pd.DataFrame({
        "category": ["X","Y","Z","X","Y","Z","X","Y"],
        "value":    [10, 20, 15, 12, 18, 14, 11, 22],
        "flag":     ["yes","no","yes","yes","no","yes","no","yes"],
    })


@pytest.fixture
def bank_schema(bank_df):
    """Schema profile for bank_df."""
    import sys; sys.path.insert(0, ".")
    from app.services.schema_profiler import profile_dataframe
    return profile_dataframe(bank_df)


@pytest.fixture
def sales_schema(sales_df):
    from app.services.schema_profiler import profile_dataframe
    return profile_dataframe(sales_df)