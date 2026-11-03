from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.indexing import index_paper
from app.services.jobs import jobs
from app.store import paper_store

logger = logging.getLogger(__name__)


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
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "api": settings.api_prefix,
        "docs": "/docs",
    }
