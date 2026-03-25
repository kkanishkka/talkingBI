"""
main.py  (updated — add one line to register the /dashboard router)
All existing routers are kept exactly as-is.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import upload, analyze, recommend, layouts, insights, coverage
from app.api.routes import dashboard          # ← only new import

app = FastAPI(title="TalkingBI")

# Allow the Vite dev server (port 5173) during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing routers — unchanged
app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(recommend.router)
app.include_router(layouts.router)
app.include_router(insights.router)
app.include_router(coverage.router)

# New combined router
app.include_router(dashboard.router)          # ← only new line


@app.get("/health")
def health():
    return {"status": "ok"}