"""
app/schemas/connection.py
Pydantic request schemas for API routes.
"""
from pydantic import BaseModel, Field


class DBConnectionRequest(BaseModel):
    connection_string: str = Field(..., min_length=1)


class TableSelectionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    table_name: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    prompt:     str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message:    str = Field(..., min_length=1)