"""Retrieval-augmented answering with a deterministic fallback."""

from __future__ import annotations

import asyncio
import logging
import re

from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.core.config import settings
from app.models.schemas import AnswerResponse, Citation
from app.services.indexing import Chunk, get_index
from app.services.llm import chat
from app.services.text import best_window
from app.store import paper_store

logger = logging.getLogger(__name__)


def expand_hits(
    hits: list[tuple[Chunk, float]], window: int = 1, limit: int = 18
) -> list[tuple[Chunk, float]]:
    """Add adjacent blocks so line-level OCR/PDF chunks keep their context."""

    expanded: list[tuple[Chunk, float]] = []
    seen: set[str] = set()
    for chunk, score in hits:
        paper = paper_store.get(chunk.paper_id)
        if paper is None:
            if chunk.id not in seen:
                seen.add(chunk.id)
                expanded.append((chunk, score))
            continue
        block_ids = [block.id for block in paper.blocks]
        try:
            index = block_ids.index(chunk.block_id)
        except ValueError:
            if chunk.id not in seen:
                seen.add(chunk.id)
                expanded.append((chunk, score))
            continue
        for offset in range(-window, window + 1):
            position = index + offset
            if not 0 <= position < len(paper.blocks):
                continue
            block = paper.blocks[position]
            chunk_id = f"{paper.id}:{block.id}"
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            expanded.append(
                (
                    Chunk(
                        id=chunk_id,
                        paper_id=paper.id,
                        paper_title=paper.title,
                        page=block.page,
                        block_id=block.id,
                        text=block.text,
                        bbox=block.bbox,
                        bbox_space=block.bbox_space,
                        section_path=tuple(block.section_path),
                    ),
                    score if offset == 0 else score * 0.4,
                )
            )
    return expanded[:limit]


def retrieve_hits(
    question: str,
    paper_ids: list[str] | None = None,
    top_k: int = 6,
) -> list[tuple[Chunk, float]]:
    """Retrieve per paper so a multi-paper question keeps every source."""

    index = get_index()
    if not paper_ids or len(paper_ids) <= 1:
        return expand_hits(
            index.search(question, paper_ids=paper_ids, top_k=top_k)
        )
    per_paper = max(3, top_k)
    buckets = [
        index.search(question, paper_ids=[paper_id], top_k=per_paper)
        for paper_id in paper_ids
    ]
    interleaved: list[tuple[Chunk, float]] = []
    for rank in range(per_paper):
        for bucket in buckets:
            if rank < len(bucket):
                interleaved.append(bucket[rank])
    return expand_hits(interleaved, limit=max(18, 6 * len(paper_ids)))


def _citations_from_hits(
    hits: list[tuple[Chunk, float]], question: str
) -> list[Citation]:
    return [
        Citation(
            paper_id=chunk.paper_id,
            paper_title=chunk.paper_title,
            page=chunk.page,
            block_id=chunk.block_id,
            quote=best_window(chunk.text, question, 600),
            score=round(score, 4),
            bbox=chunk.bbox,
            bbox_space=chunk.bbox_space,  # type: ignore[arg-type]
        )
        for chunk, score in hits
    ]


def _extractive_answer(
    question: str, hits: list[tuple[Chunk, float]]
) -> str:
    if not hits:
        return "库中未找到足够依据。请先上传论文，或换一个更具体的问题。"
    lines = ["根据检索到的原文，最相关的内容如下："]
    for index, (chunk, _score) in enumerate(hits, start=1):
        quote = best_window(chunk.text, question, 900).replace("\n", " ").strip()
        lines.append(f"[{index}] {quote} [原文声明]")
    lines.append("")
    lines.append("依据：" + "、".join(f"[{i}]" for i in range(1, len(hits) + 1)))
    return "\n".join(lines)


def _chunk_text(text: str, size: int = 6) -> list[str]:
    return re.findall(rf".{{1,{size}}}", text, flags=re.S)


def _grounding_check(answer: str, citations: list[Citation]) -> tuple[bool, int]:
    """A citation marker is only valid if it points at a real retrieved chunk."""

    if not citations:
        return False, 0
    markers = [int(value) for value in re.findall(r"\[(\d{1,2})\]", answer)]
    valid = [value for value in markers if 1 <= value <= len(citations)]
    return bool(valid), len(valid)


async def answer_from_hits(
    question: str, hits: list[tuple[Chunk, float]]
) -> AnswerResponse:
    citations = _citations_from_hits(hits, question)
    context_blocks = [best_window(chunk.text, question, 1100) for chunk, _ in hits]
    answer = await chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(question, context_blocks)},
        ]
    )
    model = settings.llm_model
    if not answer:
        answer = _extractive_answer(question, hits)
        model = "extractive-fallback"
    grounded, marker_count = _grounding_check(answer, citations)
    return AnswerResponse(
        answer=answer,
        citations=citations,
        trace=[
            f"answer: {model}",
            f"verify: {marker_count} 个引用标记可定位到 {len(citations)} 条原文锚点",
        ],
        model=model,
        grounded=grounded,
    )


async def answer_question(
    question: str,
    paper_ids: list[str] | None = None,
    top_k: int = 6,
) -> AnswerResponse:
    hits = retrieve_hits(question, paper_ids=paper_ids, top_k=top_k)
    response = await answer_from_hits(question, hits)
    trace = [
        f"plan: 在 {len(paper_ids) if paper_ids else '全部'} 篇论文中检索并作答",
        f"retrieve: 命中 {len(hits)} 个片段",
        *response.trace,
        f"verify: {len(response.citations)} 条引用锚点",
    ]
    return response.model_copy(update={"trace": trace})


async def stream_answer(
    question: str,
    paper_ids: list[str] | None = None,
    top_k: int = 6,
):
    """Yield SSE-shaped dicts: {"event": ..., "data": ...}."""

    yield {"event": "status", "data": {"stage": "retrieve"}}
    response = await answer_question(question, paper_ids=paper_ids, top_k=top_k)
    yield {
        "event": "citations",
        "data": [citation.model_dump() for citation in response.citations],
    }
    yield {"event": "status", "data": {"stage": "answer", "model": response.model}}
    for piece in _chunk_text(response.answer):
        yield {"event": "token", "data": {"text": piece}}
        await asyncio.sleep(0)
    yield {
        "event": "done",
        "data": {
            "grounded": response.grounded,
            "trace": response.trace,
            "model": response.model,
        },
    }
