from __future__ import annotations

import io
from fastapi import APIRouter, File, HTTPException, UploadFile
import pandas as pd

from app.services.schema_profiler import profile_dataframe

router = APIRouter(tags=["upload"])


def _load_dataframe(file: UploadFile) -> pd.DataFrame:
    filename = file.filename or ""
    ext = filename.lower().split(".")[-1]

    file_bytes = file.file.read()

    if ext == "csv":
        return pd.read_csv(io.BytesIO(file_bytes))

    if ext in {"xlsx", "xls"}:
        return pd.read_excel(io.BytesIO(file_bytes))

    raise HTTPException(
        status_code=400,
        detail="Unsupported file type. Please upload a CSV or Excel file.",
    )


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    try:
        df = _load_dataframe(file)
        profile = profile_dataframe(df)

        return {
            "filename": file.filename,
            "message": "File uploaded and profiled successfully.",
            "profile": profile,
            "preview_rows": df.head(5).fillna("").to_dict(orient="records"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process file: {str(exc)}",
        ) from exc