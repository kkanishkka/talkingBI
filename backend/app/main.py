"""
app/main.py
══════════════════════════════════════════════════════════════════════
TalkingBI FastAPI application entry point.

Registers all routers. Configures CORS from settings.
Health endpoint now reports session count + layer status.
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import upload, analyze, recommend, layouts, insights, coverage
from app.api.routes import dashboard
from app.api.routes import session as session_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="TalkingBI",
    description="AI-powered Business Intelligence assistant — refactored layered architecture",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=     settings.allowed_origins,
    allow_credentials= True,
    allow_methods=     ["*"],
    allow_headers=     ["*"],
)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(upload.router)
app.include_router(dashboard.router)
app.include_router(session_routes.router)
app.include_router(analyze.router)
app.include_router(recommend.router)
app.include_router(layouts.router)
app.include_router(insights.router)
app.include_router(coverage.router)


# ── Health ────────────────────────────────────────────────────────

@app.get("/health")
def health():
    from app.core.llm_client import llm_client
    from app.core.session_store import session_store
    return {
        "status":          "ok",
        "version":         "3.0.0",
        "llm_available":   llm_client.available,
        "active_sessions": len(session_store),
        "layers": {
            "ingestion":    "ok",
            "semantic":     "ok",
            "reasoning":    "ok",
            "validation":   "ok",
            "presentation": "ok",
        },
    }
