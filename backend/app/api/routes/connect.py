from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.session_store import session_store
from app.layers.ingestion.datasources.supabase import SupabaseDataSource
from app.layers.semantic.schema_profiler import build_schema_context, profile_dataframe
from app.schemas.connection import DBConnectionRequest, TableSelectionRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["connect"])


@router.post("/connect")
def connect_database(payload: DBConnectionRequest):
    try:
        ds = SupabaseDataSource(payload.connection_string)
        meta = ds.test_connection()
        tables = []

        for table_name in ds.list_tables():
            try:
                with ds.engine.connect() as conn:
                    row_count_res = conn.execute(
                        text(f'SELECT COUNT(*) FROM public."{table_name}"')
                    )
                    row_count = row_count_res.scalar()

                    col_count_res = conn.execute(
                        text("""
                            SELECT COUNT(*)
                            FROM information_schema.columns
                            WHERE table_schema='public' AND table_name = :name
                        """),
                        {"name": table_name},
                    )
                    col_count = col_count_res.scalar()

                    type_res = conn.execute(
                        text("""
                            SELECT table_type
                            FROM information_schema.tables
                            WHERE table_schema='public' AND table_name = :name
                        """),
                        {"name": table_name},
                    )
                    table_type = type_res.scalar()

                priority = "analytical" if (
                    table_type == "VIEW"
                    or table_name.startswith(("fact_", "raw_", "vw_"))
                    or ((row_count or 0) > 1000 and (col_count or 0) > 5)
                ) else "dimension"

                tables.append({
                    "name": table_name,
                    "row_count": int(row_count or 0),
                    "col_count": int(col_count or 0),
                    "type": table_type or "BASE TABLE",
                    "priority": priority,
                })
            except Exception as table_exc:
                logger.warning("Skipping table %s due to metadata error: %s", table_name, table_exc)
                continue

        tables.sort(
            key=lambda t: (
                t["priority"] == "dimension",
                -(t["row_count"] * t["col_count"]),
                t["name"],
            )
        )

        session_id = session_store.new_session()
        session_store.set_datasource(
            session_id=session_id,
            datasource_type="supabase",
            connection_string=payload.connection_string,
        )

        return {
            "message": "Database connected successfully.",
            "session_id": session_id,
            "connection": meta,
            "tables": tables,
        }

    except Exception as exc:
        logger.exception("Database connection failed")
        raise HTTPException(status_code=400, detail=f"Connection failed: {exc}")


@router.post("/select-table")
def select_table(payload: TableSelectionRequest):
    connection_string = session_store.get_connection_string(payload.session_id)
    if not connection_string:
        raise HTTPException(status_code=404, detail="Session not found or database not connected.")

    try:
        ds = SupabaseDataSource(connection_string)
        table_schema = ds.get_table_schema(payload.table_name)

        df = ds.load_dataframe(payload.table_name, limit=50000)
        profile = profile_dataframe(df)
        schema_ctx = build_schema_context(profile)

        col_names = profile["dataset_summary"]["column_names"]
        row_count = profile["dataset_summary"]["rows"]

        session_store.set_selected_table(
            session_id=payload.session_id,
            table_name=payload.table_name,
            table_schema=table_schema,
        )
        session_store.set_schema(
            payload.session_id,
            schema_ctx,
            col_names,
            row_count,
        )

        return {
            "message": f"Table '{payload.table_name}' selected.",
            "session_id": payload.session_id,
            "table_name": payload.table_name,
            "table_schema": table_schema,
            "dataset_summary": profile["dataset_summary"],
        }
    except Exception as exc:
        logger.exception("Table selection failed")
        raise HTTPException(status_code=400, detail=f"Table selection failed: {exc}")