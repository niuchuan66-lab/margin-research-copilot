from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import DiscoveryHit, DiscoveryRequest, RecommendRequest
from app.services import discovery as discovery_service

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/search", response_model=list[DiscoveryHit])
async def search(payload: DiscoveryRequest) -> list[DiscoveryHit]:
    return await discovery_service.search(
        payload.query,
        source=payload.source,
        limit=payload.limit,
    )


@router.post("/recommend", response_model=list[DiscoveryHit])
async def recommend(payload: RecommendRequest) -> list[DiscoveryHit]:
    return await discovery_service.recommend(payload.paper_ids, limit=payload.limit)
