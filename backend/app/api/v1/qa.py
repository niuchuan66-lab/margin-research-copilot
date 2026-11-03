from __future__ import annotations

import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.agent.graph import run_agent
from app.models.schemas import AnswerResponse, AskRequest
from app.services.qa import stream_answer

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/ask", response_model=AnswerResponse)
async def ask(payload: AskRequest) -> AnswerResponse:
    return await run_agent(
        payload.question,
        paper_ids=payload.paper_ids,
        top_k=payload.top_k,
    )


@router.post("/stream")
async def stream(payload: AskRequest) -> StreamingResponse:
    return _sse_response(payload.question, payload.paper_ids, payload.top_k)


@router.get("/stream")
async def stream_get(
    question: str = Query(min_length=2),
    paper_ids: str = "",
    top_k: int = Query(default=6, ge=1, le=20),
) -> StreamingResponse:
    ids = [item for item in paper_ids.split(",") if item]
    return _sse_response(question, ids, top_k)


def _sse_response(question: str, paper_ids: list[str], top_k: int) -> StreamingResponse:
    async def generate():
        async for event in stream_answer(question, paper_ids=paper_ids, top_k=top_k):
            payload = json.dumps(event["data"], ensure_ascii=False)
            yield f"event: {event['event']}\ndata: {payload}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
