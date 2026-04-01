"""
main.py
All routers registered. No imports from deleted files.
Deleted files (intent_parser, chart_recommender, layout_generator) are
only referenced by route files — those route files are now fixed.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import upload, analyze, recommend, layouts, insights, coverage
from app.api.routes import dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="TalkingBI",
    description="AI-powered Business Intelligence assistant",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(recommend.router)
app.include_router(layouts.router)
app.include_router(insights.router)
app.include_router(coverage.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    from app.core.llm_client import llm_client
    from app.core.session_store import session_store
    return {
        "status":          "ok",
        "version":         "2.0.0",
        "llm_available":   llm_client.available,
        "active_sessions": len(session_store),
    }