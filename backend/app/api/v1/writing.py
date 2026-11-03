from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    ChartRequest,
    ChartResponse,
    FigureRequest,
    FigureResponse,
    OutlineRequest,
    OutlineResponse,
)
from app.services.writing import (
    build_outline_llm,
    csv_to_chart_llm,
    render_figure,
)
from app.store import paper_store

router = APIRouter(prefix="/writing", tags=["writing"])


@router.post("/outline", response_model=OutlineResponse)
async def outline(payload: OutlineRequest) -> OutlineResponse:
    if payload.paper_ids:
        papers = [paper_store.get(paper_id) for paper_id in payload.paper_ids]
        papers = [paper for paper in papers if paper is not None]
    else:
        papers = [
            paper for paper in paper_store.list() if paper.status.value == "ready"
        ][:8]
    return await build_outline_llm(payload.idea, papers, payload.language)


@router.post("/figure", response_model=FigureResponse)
def figure(payload: FigureRequest) -> FigureResponse:
    try:
        return render_figure(payload.kind, payload.spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chart", response_model=ChartResponse)
async def chart(payload: ChartRequest) -> ChartResponse:
    try:
        return await csv_to_chart_llm(
            payload.csv, payload.title, payload.chart_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
