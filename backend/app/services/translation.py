"""Bilingual translation that preserves block ids and bboxes for the reader."""

from __future__ import annotations

import re

from app.agent.prompts import TRANSLATION_SYSTEM_PROMPT
from app.core.config import settings
from app.models.schemas import Block, TranslatedBlock
from app.services.llm import chat


def _lines(blocks: list[Block]) -> str:
    return "\n".join(
        f"{index + 1}|||{block.text[:2000]}" for index, block in enumerate(blocks)
    )


async def translate_text(
    text: str, target_lang: str = "zh-CN"
) -> tuple[str | None, str]:
    """Translate a user-selected passage without touching block ids."""

    if not settings.llm_configured:
        return None, "not_configured"
    answer = await chat(
        [
            {
                "role": "system",
                "content": (
                    "你是学术翻译。只输出译文，保留公式、代码、数字和引用标记；"
                    "不添加解释，不编造原文没有的内容。"
                ),
            },
            {
                "role": "user",
                "content": f"目标语言：{target_lang}\n\n{text}",
            },
        ],
        temperature=0.0,
        max_tokens=1600,
    )
    if not answer or not answer.strip():
        return None, "error"
    return answer.strip(), "ok"


async def translate_blocks(
    blocks: list[Block],
    target_lang: str = "zh-CN",
) -> list[TranslatedBlock]:
    if not blocks:
        return []
    if not settings.llm_configured:
        return [
            TranslatedBlock(
                block_id=block.id,
                page=block.page,
                bbox=block.bbox,
                source=block.text,
                translation=None,
                status="not_configured",
            )
            for block in blocks
        ]

    answer = await chat(
        [
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"目标语言：{target_lang}\n\n{_lines(blocks)}",
            },
        ],
        temperature=0.0,
        max_tokens=4000,
    )
    if not answer:
        return [
            TranslatedBlock(
                block_id=block.id,
                page=block.page,
                bbox=block.bbox,
                source=block.text,
                translation=None,
                status="error",
            )
            for block in blocks
        ]

    translations: dict[int, str] = {}
    for line in answer.splitlines():
        if "|||" not in line:
            continue
        left, right = line.split("|||", 1)
        digits = re.sub(r"\D", "", left)
        if digits:
            translations[int(digits)] = right.strip()

    return [
        TranslatedBlock(
            block_id=block.id,
            page=block.page,
            bbox=block.bbox,
            source=block.text,
            translation=translations.get(index + 1),
            status="ok" if translations.get(index + 1) else "error",
        )
        for index, block in enumerate(blocks)
    ]
