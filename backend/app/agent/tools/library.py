"""Tools over the local library: hybrid retrieval and grounded answering."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.services.qa import answer_from_hits, retrieve_hits

logger = logging.getLogger(__name__)


class LibrarySearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    paper_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=6, ge=1, le=20)


class LibraryAnswerArgs(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    paper_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=6, ge=1, le=20)


def _hit_dict(chunk, score: float) -> dict[str, Any]:
    return {
        "paper_id": chunk.paper_id,
        "paper_title": chunk.paper_title,
        "page": chunk.page,
        "block_id": chunk.block_id,
        "text": chunk.text[:300],
        "score": round(score, 4),
    }


class LibrarySearchTool(Tool):
    name = "library.search"
    description = "在本地论文库中做混合检索（BM25+重叠+可选向量），返回命中片段与页码。"
    args_model = LibrarySearchArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        search_args: LibrarySearchArgs = args  # type: ignore[assignment]
        try:
            hits = retrieve_hits(
                search_args.query,
                paper_ids=search_args.paper_ids or context.paper_ids or None,
                top_k=search_args.top_k,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("library.search failed: %s", exc)
            return ToolResult(ok=False, summary=f"检索失败：{exc}")
        if not hits:
            return ToolResult(
                ok=True,
                summary="库中未命中任何片段。",
                data={"hits": [], "count": 0},
            )
        pages = sorted({hit.page for hit, _ in hits})
        return ToolResult(
            ok=True,
            summary=f"命中 {len(hits)} 个片段（页码 {pages}）",
            data={
                "count": len(hits),
                "hits": [_hit_dict(chunk, score) for chunk, score in hits],
            },
        )


class LibraryAnswerTool(Tool):
    name = "library.answer"
    description = (
        "基于本地论文库回答事实性问题，回答必须带引用标记 [n] 与原文页码。"
    )
    args_model = LibraryAnswerArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        answer_args: LibraryAnswerArgs = args  # type: ignore[assignment]
        try:
            hits = retrieve_hits(
                answer_args.question,
                paper_ids=answer_args.paper_ids or context.paper_ids or None,
                top_k=answer_args.top_k,
            )
            response = await answer_from_hits(answer_args.question, hits)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("library.answer failed: %s", exc)
            return ToolResult(ok=False, summary=f"回答失败：{exc}")
        citations = [citation.model_dump() for citation in response.citations]
        return ToolResult(
            ok=True,
            summary=(
                f"回答 {len(response.answer)} 字，"
                f"{len(citations)} 条原文引用（grounded={response.grounded}）"
            ),
            data={
                "answer": response.answer,
                "grounded": response.grounded,
                "model": response.model,
            },
            citations=citations,
        )
