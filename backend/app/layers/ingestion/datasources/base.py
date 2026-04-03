from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class AbstractDataSource(ABC):
    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_tables(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_table_schema(self, table_name: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def load_dataframe(self, table_name: str, limit: int | None = None) -> pd.DataFrame:
        raise NotImplementedError