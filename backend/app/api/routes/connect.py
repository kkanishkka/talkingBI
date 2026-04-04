"""
app/api/routes/connect.py — v2 (auto table selection)

Changes from v1:
  ① POST /connect now auto-selects the best table immediately after
    listing tables. The client no longer needs to call /select-table
    unless it wants to override the selection.

  ② The /connect response now includes:
      "auto_selected_table": "<name>"   ← best table
      "selection_reason": "<why>"
      "dataset_summary": {...}          ← profile of auto-selected table
      (so the frontend can go straight to the chat view)

  ③ POST /select-table still works for manual override — the frontend
    can call it if the user explicitly chooses a different table.

  ④ table_selector.select_best_table_with_reason() is used for scoring.
    Falls back to the first "analytical" table if selector fails.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.session_store import session_store
from app.layers.ingestion.datasources.supabase import SupabaseDataSource
from app.layers.ingestion.table_selector import select_best_table_with_reason
from app.layers.semantic.schema_profiler import build_schema_context, profile_dataframe
from app.schemas.connection import DBConnectionRequest, TableSelectionRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["connect"])


# ═══════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════

def _list_tables(ds: SupabaseDataSource) -> list[dict]:
    """Fetch table metadata list (same logic as before)."""
    tables = []
    for table_name in ds.list_tables():
        try:
            with ds.engine.connect() as conn:
                row_count = conn.execute(
                    text(f'SELECT COUNT(*) FROM public."{table_name}"')
                ).scalar()

                col_count = conn.execute(
                    text("""
                        SELECT COUNT(*)
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name = :name
                    """),
                    {"name": table_name},
                ).scalar()

                table_type = conn.execute(
                    text("""
                        SELECT table_type
                        FROM information_schema.tables
                        WHERE table_schema='public' AND table_name = :name
                    """),
                    {"name": table_name},
                ).scalar()

            priority = "analytical" if (
                table_type == "VIEW"
                or table_name.startswith(("fact_", "raw_", "vw_"))
                or ((row_count or 0) > 1000 and (col_count or 0) > 5)
            ) else "dimension"

            tables.append({
                "name":      table_name,
                "row_count": int(row_count or 0),
                "col_count": int(col_count or 0),
                "type":      table_type or "BASE TABLE",
                "priority":  priority,
            })
        except Exception as exc:
            logger.warning("Skipping table %s: %s", table_name, exc)

    tables.sort(
        key=lambda t: (
            t["priority"] == "dimension",
            -(t["row_count"] * t["col_count"]),
            t["name"],
        )
    )
    return tables


def _load_and_profile_table(
    ds:         SupabaseDataSource,
    table_name: str,
) -> tuple[dict, dict]:
    """Load a table, profile it, return (table_schema, profile)."""
    table_schema = ds.get_table_schema(table_name)
    df           = ds.load_dataframe(table_name, limit=50000)
    profile      = profile_dataframe(df)
    return table_schema, profile


# ═══════════════════════════════════════════════════════════════════
# routes
# ═══════════════════════════════════════════════════════════════════

@router.post("/connect")
def connect_database(payload: DBConnectionRequest):
    """
    Connect to a Supabase database.
    Auto-selects the best analytical table and profiles it immediately.
    Returns the session_id, table list, and dashboard-ready profile.
    """
    try:
        ds   = SupabaseDataSource(payload.connection_string)
        meta = ds.test_connection()

        tables = _list_tables(ds)
        if not tables:
            raise HTTPException(status_code=400, detail="No tables found in the database.")

        # ── Auto-select best table ────────────────────────────────
        # Use a generic "overview" query when no specific user query is
        # provided yet — scoring will favour large analytical tables.
        auto_query = getattr(payload, "initial_query", "") or "overview analysis"
        try:
            selected_name, selection_reason = select_best_table_with_reason(
                query=             auto_query,
                tables=            tables,
                connection_string= payload.connection_string,
            )
        except Exception as exc:
            # Fallback: first analytical table
            logger.warning("table_selector failed: %s — falling back to first table", exc)
            selected_name    = tables[0]["name"]
            selection_reason = "Defaulted to first available table."

        # ── Profile the selected table ────────────────────────────
        table_schema, profile = _load_and_profile_table(ds, selected_name)
        schema_ctx = build_schema_context(profile)
        col_names  = profile["dataset_summary"]["column_names"]
        row_count  = profile["dataset_summary"]["rows"]

        # ── Create session ────────────────────────────────────────
        session_id = session_store.new_session()
        session_store.set_datasource(
            session_id=        session_id,
            datasource_type=   "supabase",
            connection_string= payload.connection_string,
        )
        session_store.set_selected_table(
            session_id=   session_id,
            table_name=   selected_name,
            table_schema= table_schema,
        )
        session_store.set_schema(
            session_id=     session_id,
            schema=         schema_ctx,
            column_names=   col_names,
            row_count=      row_count,
            schema_profile= profile,
        )

        logger.info(
            "connect: session=%s auto_selected='%s' (%d rows)",
            session_id[:8], selected_name, row_count,
        )

        return {
            "message":            "Database connected and table auto-selected.",
            "session_id":         session_id,
            "connection":         meta,
            "tables":             tables,
            # ── new fields ──
            "auto_selected_table": selected_name,
            "selection_reason":    selection_reason,
            "dataset_summary":     profile["dataset_summary"],
            "table_ready":         True,   # frontend can skip the table-select step
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Database connection failed")
        raise HTTPException(status_code=400, detail=f"Connection failed: {exc}")


@router.post("/select-table")
def select_table(payload: TableSelectionRequest):
    """
    Manual table override — called only when user explicitly chooses
    a different table than the auto-selected one.
    """
    connection_string = session_store.get_connection_string(payload.session_id)
    if not connection_string:
        raise HTTPException(
            status_code=404,
            detail="Session not found or database not connected.",
        )

    try:
        ds           = SupabaseDataSource(connection_string)
        table_schema, profile = _load_and_profile_table(ds, payload.table_name)
        schema_ctx   = build_schema_context(profile)
        col_names    = profile["dataset_summary"]["column_names"]
        row_count    = profile["dataset_summary"]["rows"]

        session_store.set_selected_table(
            session_id=   payload.session_id,
            table_name=   payload.table_name,
            table_schema= table_schema,
        )
        session_store.set_schema(
            payload.session_id,
            schema_ctx,
            col_names,
            row_count,
            schema_profile=profile,
        )

        return {
            "message":       f"Table '{payload.table_name}' selected.",
            "session_id":    payload.session_id,
            "table_name":    payload.table_name,
            "table_schema":  table_schema,
            "dataset_summary": profile["dataset_summary"],
        }

    except Exception as exc:
        logger.exception("Table selection failed")
        raise HTTPException(status_code=400, detail=f"Table selection failed: {exc}")