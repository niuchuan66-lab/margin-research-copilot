"""Tool-calling agent endpoint: POST /agent/run streams plan and tool events."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent.executor import run_plan
from app.agent.router import plan_request
from app.agent.tools.base import ToolContext
from app.models.schemas import AgentRunRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

_END = object()


@router.post("/run")
async def run(payload: AgentRunRequest) -> StreamingResponse:
    """SSE order: plan → tool_start/tool_result* → answer → citations → done."""

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: str, data) -> None:
            await queue.put((event, data))

        async def produce() -> None:
            try:
                plan = await plan_request(payload.question, payload.paper_ids)
                await emit(
                    "plan",
                    {
                        "intent": plan.intent,
                        "steps": [
                            {"tool": step.tool, "args": step.args}
                            for step in plan.steps
                        ],
                    },
                )
                context = ToolContext(
                    question=payload.question,
                    paper_ids=payload.paper_ids,
                    user_language="zh",
                )
                result = await run_plan(plan, context, emit)
                await emit(
                    "answer",
                    {"answer": result.answer, "model": result.model},
                )
                await emit("citations", result.citations)
                await emit(
                    "done",
                    {"trace": result.trace, "model": result.model},
                )
            except Exception as exc:
                logger.exception("Agent run failed")
                await emit(
                    "error",
                    {"message": "Agent 执行失败", "detail": str(exc)[:300]},
                )
            finally:
                await queue.put(_END)

        producer = asyncio.create_task(produce())
        try:
            while True:
                item = await queue.get()
                if item is _END:
                    break
                event, data = item
                payload_text = json.dumps(data, ensure_ascii=False)
                yield f"event: {event}\ndata: {payload_text}\n\n"
        finally:
            if not producer.done():
                producer.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
