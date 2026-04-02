"""
app/layers/ingestion/loader.py
══════════════════════════════════════════════════════════════════════
Ingestion Layer: file loading + validation.

Improvements over original:
  - Raises typed IngestionError (not bare HTTPException from inside a service)
  - Validates file size, column count, and minimum row count before profiling
  - Extensible: add DB connector by implementing AbstractDataSource
  - Separates reading from validation (two distinct concerns)
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import pandas as pd
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import IngestionError

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {"csv", "xlsx", "xls"}


# ── Loading ───────────────────────────────────────────────────────

def load_dataframe(file: UploadFile) -> tuple[pd.DataFrame, str]:
    """
    Load a file into a DataFrame.

    Returns:
        (df, filename)

    Raises:
        IngestionError on unsupported type, parse failure, or size limit.
    """
    filename = file.filename or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext not in _SUPPORTED_EXTENSIONS:
        raise IngestionError(
            f"Unsupported file type '.{ext}'. "
            f"Please upload a CSV or Excel (.xlsx / .xls) file.",
            retryable=False,
        )

    raw = file.file.read()
    _check_size(raw, filename)

    try:
        if ext == "csv":
            df = _load_csv(raw)
        else:
            df = _load_excel(raw)
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(
            f"Failed to parse '{filename}': {exc}. "
            f"Check the file is not corrupt or password-protected.",
            retryable=False,
        ) from exc

    logger.info("Loaded '%s': %d rows × %d cols", filename, len(df), len(df.columns))
    return df, filename


def _load_csv(raw: bytes) -> pd.DataFrame:
    # Try auto-detecting separator; fall back to comma
    try:
        return pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
    except Exception:
        return pd.read_csv(io.BytesIO(raw))


def _load_excel(raw: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(raw))


def _check_size(raw: bytes, filename: str) -> None:
    mb = len(raw) / (1024 * 1024)
    if mb > settings.max_upload_mb:
        raise IngestionError(
            f"File '{filename}' is {mb:.1f} MB — "
            f"maximum allowed is {settings.max_upload_mb} MB.",
            retryable=False,
        )


# ── Post-load validation ──────────────────────────────────────────

def validate_dataframe(df: pd.DataFrame, filename: str) -> list[str]:
    """
    Validate a loaded DataFrame and return a list of warning strings.
    Raises IngestionError for hard failures; returns warnings for soft issues.
    """
    warnings: list[str] = []

    if df.empty or len(df) == 0:
        raise IngestionError(
            f"'{filename}' is empty — no rows found.",
            retryable=False,
        )

    if len(df.columns) == 0:
        raise IngestionError(
            f"'{filename}' has no columns.",
            retryable=False,
        )

    if len(df.columns) > settings.max_columns:
        raise IngestionError(
            f"'{filename}' has {len(df.columns)} columns — "
            f"maximum supported is {settings.max_columns}. "
            f"Consider selecting a subset of columns.",
            retryable=False,
        )

    if len(df) < 5:
        warnings.append(
            f"Dataset has only {len(df)} rows — results may not be statistically meaningful."
        )

    # Detect mostly-empty columns
    null_pcts = df.isnull().mean()
    all_null = null_pcts[null_pcts == 1.0].index.tolist()
    if all_null:
        warnings.append(
            f"Columns with 100% missing values will be excluded from analysis: "
            f"{', '.join(all_null[:5])}."
        )
        df.drop(columns=all_null, inplace=True)

    return warnings
