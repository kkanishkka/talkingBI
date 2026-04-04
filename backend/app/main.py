from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analyze, coverage, insights, layouts, recommend
from app.api.routes import session as session_routes
from app.api.routes.ask import router as ask_router
from app.api.routes.connect import router as connect_router
from app.api.routes.chat import router as chat_router
from app.api.routes.voice import router as voice_router   # NEW
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="TalkingBI",
    description="Conversational AI BI assistant — voice, chat, and dashboard",
    version="5.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connect_router)
app.include_router(ask_router)
app.include_router(chat_router)
app.include_router(voice_router)          # NEW
app.include_router(session_routes.router)
app.include_router(analyze.router)
app.include_router(recommend.router)
app.include_router(layouts.router)
app.include_router(insights.router)
app.include_router(coverage.router)


@app.get("/health")
def health():
    from app.core.llm_client import llm_client
    from app.core.session_store import session_store
    import os

    return {
        "status":          "ok",
        "version":         "5.0.0",
        "llm_available":   llm_client.available,
        "stt_available":   bool(os.getenv("OPENAI_API_KEY")),
        "tts_available":   bool(os.getenv("OPENAI_API_KEY")),
        "active_sessions": len(session_store),
        "layers": {
            "datasource":   "ok",
            "semantic":     "ok",
            "reasoning":    "ok",
            "followup":     "ok",
            "validation":   "ok",
            "presentation": "ok",
            "composer":     "ok",
            "voice":        "ok",
        },
    }