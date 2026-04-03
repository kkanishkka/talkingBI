from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.layers.ingestion.datasources.base import AbstractDataSource


class SupabaseDataSource(AbstractDataSource):
    """
    Supabase ko PostgreSQL datasource ki tarah use karte hain.
    Read-only user ke saath connect karo.
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine: Engine = create_engine(
            connection_string,
            pool_pre_ping=True,
            future=True,
        )

    def test_connection(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("select current_database(), current_schema(), version()")
            ).fetchone()

        return {
            "status": "connected",
            "database": row[0] if row else None,
            "schema": row[1] if row else None,
            "version": row[2] if row else None,
        }

    def list_tables(self) -> list[str]:
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_type IN ('BASE TABLE', 'VIEW')
                    ORDER BY table_name
                """)
            )
            tables = [row[0] for row in result.fetchall()]
        return tables

    def get_table_schema(self, table_name: str) -> dict[str, Any]:
        # Use list_tables logic for consistency with views
        if table_name not in self.list_tables():
            raise ValueError(f"Table/view '{table_name}' not found in public schema.")

        inspector = inspect(self.engine)
        cols = inspector.get_columns(table_name, schema="public")
        pk = inspector.get_pk_constraint(table_name, schema="public") or {}

        return {
            "table_name": table_name,
            "schema": "public",
            "primary_key": pk.get("constrained_columns", []),
            "columns": [
                {
                    "name": c["name"],
                    "type": str(c["type"]),
                    "nullable": c.get("nullable", True),
                }
                for c in cols
            ],
        }

    def load_dataframe(self, table_name: str, limit: int | None = 50000) -> pd.DataFrame:
        # Use list_tables for consistency (supports views)
        allowed_tables = self.list_tables()

        if table_name not in allowed_tables:
            raise ValueError(f"Table/view '{table_name}' is not allowed.")

        sql = f'SELECT * FROM public."{table_name}"'
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        return pd.read_sql(sql, self.engine)
