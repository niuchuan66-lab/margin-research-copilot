from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import agent, discovery, graph, health, papers, qa, reader, writing

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(papers.router)
api_router.include_router(qa.router)
api_router.include_router(agent.router)
api_router.include_router(reader.router)
api_router.include_router(discovery.router)
api_router.include_router(graph.router)
api_router.include_router(writing.router)
