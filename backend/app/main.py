from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.indexing import index_paper
from app.services.jobs import jobs
from app.store import paper_store

logger = logging.getLogger(__name__)

_frontend_raw = os.getenv("FRONTEND_DIST", "").strip()
_frontend_dist = Path(_frontend_raw) if _frontend_raw else None
_frontend_root = (
    _frontend_dist.resolve()
    if _frontend_dist is not None and _frontend_dist.exists()
    else None
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings.ensure_dirs()
    for paper in paper_store.list():
        if paper.status.value == "ready" and paper.blocks:
            try:
                count = index_paper(paper)
                logger.info("Reindexed %s (%s chunks)", paper.id, count)
            except Exception as exc:
                logger.warning("Reindex failed for %s: %s", paper.id, exc)
    yield
    paper_store.close()
    jobs.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Research copilot API: PDF parsing, citation-grounded RAG, "
        "bilingual reading, discovery, citation graphs and writing helpers."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["meta"])
def root():
    if _frontend_root is not None:
        return FileResponse(_frontend_root / "index.html")
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "api": settings.api_prefix,
        "docs": "/docs",
    }


if _frontend_root is not None:
    _assets = _frontend_root / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "docs", "openapi.json")):
            raise HTTPException(status_code=404, detail="Not Found")
        target = (_frontend_root / full_path).resolve()
        if full_path and _frontend_root in target.parents and target.is_file():
            return FileResponse(target)
        return FileResponse(_frontend_root / "index.html")
