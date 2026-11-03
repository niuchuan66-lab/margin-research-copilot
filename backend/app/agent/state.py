from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from app.services.indexing import Chunk


class AgentState(TypedDict):
    question: str
    paper_ids: list[str]
    top_k: int
    plan: NotRequired[list[str]]
    hits: NotRequired[list[tuple[Chunk, float]]]
    answer: NotRequired[str]
    citations: NotRequired[list[dict[str, Any]]]
    trace: NotRequired[list[str]]
    model: NotRequired[str]
