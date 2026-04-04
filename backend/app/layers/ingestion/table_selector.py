"""
app/layers/ingestion/table_selector.py
══════════════════════════════════════════════════════════════════════
Automatic Table Selector

Given a list of table metadata objects and a user query, scores each
table and returns the best match — no user prompt needed.

Scoring strategy (deterministic, dataset-agnostic):
  1. Token overlap between query tokens and table name tokens
  2. Token overlap between query tokens and column name tokens
  3. Bonus for "analytical" priority tables (large, many columns)
  4. Penalty for tiny tables (<50 rows)
  5. Optional LLM re-rank if score is too close to call

The LLM re-rank uses Groq (via llm_client) if available, otherwise
the deterministic score is used directly.

Public API:
  select_best_table(query, tables, connection_string=None) -> str
  select_best_table_with_reason(query, tables) -> (str, str)

Tables input format (same as /connect response):
  [{"name": "orders", "row_count": 5000, "col_count": 12,
    "type": "BASE TABLE", "priority": "analytical"}, ...]

Optionally pass a connection_string to fetch column names for better
scoring (column-level matching). If not provided, only table names
are scored.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — helpers
# ═══════════════════════════════════════════════════════════════════

def _tokenise(text: str) -> set[str]:
    """Lower-case alphanumeric tokens, including snake_case split."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _table_tokens(table_name: str) -> set[str]:
    return _tokenise(table_name)


def _col_tokens(col_name: str) -> set[str]:
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", col_name)
    return _tokenise(parts)


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — deterministic scorer
# ═══════════════════════════════════════════════════════════════════

def _score_table(
    query_tokens:  set[str],
    table:         dict[str, Any],
    col_names:     list[str],
) -> float:
    """
    Score a single table for relevance to the query.
    Returns a float — higher is better.
    """
    score = 0.0
    name  = table.get("name", "")

    # 1. Table name token overlap (strong signal)
    name_toks = _table_tokens(name)
    name_overlap = len(query_tokens & name_toks)
    score += name_overlap * 3.0

    # 2. Column name token overlap (each matching col adds score)
    col_overlap = 0
    for col in col_names:
        ctoks = _col_tokens(col)
        if query_tokens & ctoks:
            col_overlap += 1
    score += col_overlap * 1.0

    # 3. Analytical priority bonus
    if table.get("priority") == "analytical":
        score += 1.5

    # 4. Table type bonus (VIEWs are often pre-aggregated analytics tables)
    if table.get("type") == "VIEW":
        score += 1.0

    # 5. Size bonus — more rows / cols = more likely to be interesting
    rows = table.get("row_count") or 0
    cols = table.get("col_count") or 0
    if rows > 1000:
        score += 0.5
    if rows > 10000:
        score += 0.5
    if cols > 5:
        score += 0.3

    # 6. Penalty for very small tables
    if rows < 50:
        score -= 1.0

    return score


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — column fetcher
# ═══════════════════════════════════════════════════════════════════

def _fetch_column_names(
    connection_string: str,
    table_name:        str,
) -> list[str]:
    """Fetch column names for a table using SQLAlchemy. Returns [] on error."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :name
                    ORDER BY ordinal_position
                """),
                {"name": table_name},
            )
            return [row[0] for row in result]
    except Exception as exc:
        logger.debug("table_selector: could not fetch columns for '%s': %s", table_name, exc)
        return []


# ═══════════════════════════════════════════════════════════════════
# SECTION 4 — LLM re-ranker (optional, Groq-first)
# ═══════════════════════════════════════════════════════════════════

_SELECTOR_SYSTEM = """\
You are a database table selector. Given a user query and a list of candidate tables
with their column names, pick the SINGLE best table to answer the query.

Output ONLY a valid JSON object:
{
  "selected_table": "<exact table name>",
  "reason": "<one sentence why>"
}

Rules:
- Match by column names that relate to the query concepts
- Prefer tables with more relevant columns over smaller lookup tables
- Never hallucinate table names — use only the names provided
- Output ONLY valid JSON, no markdown
"""


def _llm_select_table(
    query:      str,
    candidates: list[dict[str, Any]],   # [{name, col_names, score}, ...]
) -> Optional[tuple[str, str]]:
    """
    Use LLM to pick the best table from candidates.
    Returns (table_name, reason) or None on failure.
    """
    try:
        from app.core.llm_client import llm_client
        if not llm_client.available:
            return None

        lines = []
        for c in candidates:
            cols_preview = ", ".join(c.get("col_names", [])[:15])
            lines.append(f"  Table: {c['name']} | Columns: {cols_preview}")

        msg  = f"User query: {query}\n\nCandidate tables:\n" + "\n".join(lines)
        data = llm_client.complete_json(_SELECTOR_SYSTEM, msg, temperature=0.0)

        if data and "selected_table" in data:
            return data["selected_table"], data.get("reason", "")

    except Exception as exc:
        logger.warning("table_selector LLM failed: %s", exc)

    return None


# ═══════════════════════════════════════════════════════════════════
# SECTION 5 — public API
# ═══════════════════════════════════════════════════════════════════

def select_best_table(
    query:             str,
    tables:            list[dict[str, Any]],
    connection_string: Optional[str] = None,
) -> str:
    """
    Return the name of the best table for the given query.
    Raises ValueError if tables is empty.
    """
    name, _ = select_best_table_with_reason(query, tables, connection_string)
    return name


def select_best_table_with_reason(
    query:             str,
    tables:            list[dict[str, Any]],
    connection_string: Optional[str] = None,
) -> tuple[str, str]:
    """
    Return (table_name, reason_string) for the best table.
    """
    if not tables:
        raise ValueError("table_selector: no tables provided")

    if len(tables) == 1:
        return tables[0]["name"], "Only one table available."

    query_tokens = _tokenise(query)

    # Fetch column names if connection available
    candidates = []
    for table in tables:
        name = table.get("name", "")
        if connection_string:
            col_names = _fetch_column_names(connection_string, name)
        else:
            col_names = []
        score = _score_table(query_tokens, table, col_names)
        candidates.append({
            "name":      name,
            "col_names": col_names,
            "score":     score,
            "table":     table,
        })

    # Sort by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)

    best  = candidates[0]
    score_gap = best["score"] - candidates[1]["score"] if len(candidates) > 1 else 99

    logger.info(
        "table_selector: top candidates: %s",
        [(c["name"], round(c["score"], 2)) for c in candidates[:3]],
    )

    # If top two scores are very close, try LLM
    if score_gap < 1.5 and len(candidates) > 1:
        top_candidates = candidates[:min(4, len(candidates))]
        llm_result = _llm_select_table(query, top_candidates)
        if llm_result:
            selected_name, reason = llm_result
            # Validate LLM returned a real table name
            if any(c["name"] == selected_name for c in candidates):
                logger.info("table_selector: LLM selected '%s': %s", selected_name, reason)
                return selected_name, reason
            logger.warning("table_selector: LLM returned unknown table '%s', using score", selected_name)

    reason = _build_reason(best, query_tokens)
    logger.info("table_selector: score-based selected '%s' (score=%.2f)", best["name"], best["score"])
    return best["name"], reason


def _build_reason(candidate: dict[str, Any], query_tokens: set[str]) -> str:
    name    = candidate["name"]
    cols    = candidate.get("col_names", [])
    matched = [c for c in cols if query_tokens & _col_tokens(c)]
    if matched:
        return (
            f"Selected '{name}' — columns '{', '.join(matched[:3])}' "
            f"match the query."
        )
    return f"Selected '{name}' as the best available analytical table."