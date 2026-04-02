"""
app/core/exceptions.py
══════════════════════════════════════════════════════════════════════
Typed exceptions for each pipeline stage.

Design goals:
  - Every failure has a clear origin (which layer failed)
  - HTTP status codes are set at the API layer, not deep in services
  - is_retryable lets the orchestrator decide whether to retry
  - user_message is safe to return to the frontend
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations


class TalkingBIError(Exception):
    """Base class for all TalkingBI pipeline errors."""
    layer:        str  = "unknown"
    is_retryable: bool = False
    user_message: str  = "An unexpected error occurred."
    http_status:  int  = 500


class IngestionError(TalkingBIError):
    """Raised by the ingestion layer (file loading, validation)."""
    layer       = "ingestion"
    http_status = 400

    def __init__(self, detail: str, retryable: bool = False) -> None:
        super().__init__(detail)
        self.user_message = detail
        self.is_retryable = retryable


class SemanticError(TalkingBIError):
    """Raised when schema profiling or semantic classification fails."""
    layer       = "semantic"
    http_status = 422

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.user_message = detail


class AmbiguityError(TalkingBIError):
    """
    Raised when the query is too ambiguous to process.
    Carries a structured clarification request for the frontend.
    """
    layer       = "reasoning"
    http_status = 200   # not an error from HTTP perspective — needs clarification
    is_retryable = False

    def __init__(self, clarification: dict) -> None:
        super().__init__("Query is ambiguous — clarification needed.")
        self.clarification = clarification
        self.user_message  = clarification.get("question", "Please clarify your query.")


class ExecutionError(TalkingBIError):
    """Raised when deterministic execution fails irrecoverably."""
    layer       = "reasoning"
    http_status = 500

    def __init__(self, detail: str, retryable: bool = True) -> None:
        super().__init__(detail)
        self.user_message = f"Analysis execution failed: {detail}"
        self.is_retryable = retryable


class ValidationError(TalkingBIError):
    """Raised when result validation finds an unrecoverable issue."""
    layer       = "validation"
    http_status = 422

    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues       = issues
        self.user_message = "Result validation failed: " + "; ".join(issues)


class PresentationError(TalkingBIError):
    """Raised by the presentation layer (viz, narration)."""
    layer       = "presentation"
    http_status = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.user_message = detail
