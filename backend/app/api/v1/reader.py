from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    BlockKind,
    Paper,
    TextTranslationRequest,
    TextTranslationResponse,
    TranslatedBlock,
    TranslationRequest,
)
from app.services.translation import translate_blocks, translate_text
from app.store import paper_store

router = APIRouter(prefix="/reader", tags=["reader"])


def _paper(paper_id: str) -> Paper:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return paper


def _heading_level(title: str, path: list[str]) -> int:
    if path:
        return max(len(path), 1)
    match = re.match(r"^(\d+(?:\.\d+)*)\.?\s", title.strip())
    if match:
        return match.group(1).count(".") + 1
    return 1


_REF_INDEX = re.compile(r"^\[(\d{1,3})\]")


@router.get("/{paper_id}/references")
def references(paper_id: str) -> list[dict]:
    paper = _paper(paper_id)
    items: list[dict] = []
    for block in paper.blocks:
        if block.kind != BlockKind.reference:
            continue
        match = _REF_INDEX.match(block.text.strip())
        items.append(
            {
                "index": int(match.group(1)) if match else None,
                "page": block.page,
                "block_id": block.id,
                "bbox": block.bbox,
                "text": block.text[:600],
            }
        )
    if items:
        return items
    return [
        {
            "index": index,
            "page": None,
            "block_id": reference.id,
            "bbox": None,
            "text": reference.raw or reference.title or "",
        }
        for index, reference in enumerate(paper.references, start=1)
    ]


@router.get("/{paper_id}/anchors")
def anchors(paper_id: str, page: int | None = None) -> list[dict]:
    paper = _paper(paper_id)
    blocks = paper.blocks if page is None else [
        block for block in paper.blocks if block.page == page
    ]
    return [
        {
            "block_id": block.id,
            "page": block.page,
            "bbox": block.bbox,
            "bbox_space": block.bbox_space,
            "kind": block.kind,
            "section_path": block.section_path,
            "text": block.text[:400],
        }
        for block in blocks
    ]


@router.get("/{paper_id}/outline")
def outline(paper_id: str) -> list[dict]:
    paper = _paper(paper_id)
    headings = [
        block for block in paper.blocks if block.kind == BlockKind.heading
    ]
    if headings:
        return [
            {
                "block_id": block.id,
                "title": block.text[:240],
                "page": block.page,
                "level": _heading_level(block.text, block.section_path),
            }
            for block in headings
        ]
    return [
        {
            "block_id": block.id,
            "title": block.text[:80],
            "page": block.page,
            "level": 1,
        }
        for block in paper.blocks[:12]
        if len(block.text.strip()) >= 20
    ]


@router.post("/translate", response_model=list[TranslatedBlock])
async def translate(payload: TranslationRequest) -> list[TranslatedBlock]:
    paper = _paper(payload.paper_id)
    selected = [
        block
        for block in paper.blocks
        if not payload.block_ids or block.id in set(payload.block_ids)
    ][:40]
    if not selected:
        raise HTTPException(status_code=400, detail="没有可翻译的文本块")
    return await translate_blocks(selected, payload.target_lang)


@router.post("/translate-text", response_model=TextTranslationResponse)
async def translate_selection(
    payload: TextTranslationRequest,
) -> TextTranslationResponse:
    translation, status = await translate_text(
        payload.text, payload.target_lang
    )
    return TextTranslationResponse(translation=translation, status=status)
