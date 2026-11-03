"""Paragraph-level diff between two versions of the same paper.

Blocks of kind heading/paragraph are matched greedily by 5-gram Jaccard
(reusing the dedup shingling), then classified into added / modified /
removed changes. Each change keeps its page + bbox anchors so the reader
can jump straight to the evidence. The LLM summary is constrained to the
change list and its page labels are validated before use.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from app.core.config import settings
from app.models.schemas import (
    Block,
    BlockKind,
    Paper,
    VersionChange,
    VersionDiffResponse,
)
from app.services.dedup import jaccard, normalize, shingles
from app.services.llm import chat

logger = logging.getLogger(__name__)

ADDED_MAX = 0.35
MODIFIED_MIN = 0.35
UNCHANGED_MIN = 0.85
MIN_BLOCK_CHARS = 40
SUMMARY_ITEM_CHARS = 500
SUMMARY_MAX_TOKENS = 1200
_VERSIONS_MIN_SIMILARITY = 0.45
_PAGE_LABEL_RE = re.compile(r"\[(新版|旧版)\s*p\.\s*(\d+)\]")
_BARE_PAGE_RE = re.compile(r"p\.\s*(\d+)")

_KIND_LABELS = {"added": "新增", "removed": "删除", "modified": "改写"}

_SYSTEM_PROMPT = (
    "你是学术论文版本审阅助手。"
    "根据给定的两版论文段落差异清单，用中文写一份简明的版本修订总结。"
)


def _body_blocks(paper: Paper) -> list[Block]:
    allowed = {BlockKind.heading, BlockKind.paragraph}
    return [
        block
        for block in paper.blocks
        if block.kind in allowed and len(normalize(block.text)) >= MIN_BLOCK_CHARS
    ]


def _whole_text(paper: Paper) -> str:
    return "\n".join(block.text for block in paper.blocks[:200])


def whole_similarity(new: Paper, old: Paper) -> float:
    return jaccard(shingles(normalize(_whole_text(new))), shingles(normalize(_whole_text(old))))


def align_paragraphs(new: Paper, old: Paper) -> list[VersionChange]:
    """Greedy paragraph alignment with an inverted shingle index.

    Unchanged paragraphs (>= 0.85) are dropped, everything else is reported
    as added / modified / removed with page + bbox anchors.
    """

    new_blocks = _body_blocks(new)
    old_blocks = _body_blocks(old)
    old_shingles = [shingles(normalize(block.text)) for block in old_blocks]
    inverted: dict[tuple[str, ...], list[int]] = {}
    for index, grams in enumerate(old_shingles):
        for gram in grams:
            inverted.setdefault(gram, []).append(index)

    used = [False] * len(old_blocks)
    changes: list[VersionChange] = []

    for new_block in new_blocks:
        new_grams = shingles(normalize(new_block.text))
        candidates: set[int] = set()
        for gram in new_grams:
            candidates.update(inverted.get(gram, ()))

        best_index = -1
        best_similarity = 0.0
        for index in candidates:
            if used[index]:
                continue
            similarity = jaccard(new_grams, old_shingles[index])
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index

        if best_index >= 0 and best_similarity >= UNCHANGED_MIN:
            used[best_index] = True
            continue
        if best_index >= 0 and best_similarity >= MODIFIED_MIN:
            used[best_index] = True
            old_block = old_blocks[best_index]
            changes.append(
                VersionChange(
                    kind="modified",
                    new_page=new_block.page,
                    new_bbox=new_block.bbox,
                    old_page=old_block.page,
                    old_bbox=old_block.bbox,
                    new_text=new_block.text,
                    old_text=old_block.text,
                    similarity=round(best_similarity, 4),
                )
            )
            continue
        changes.append(
            VersionChange(
                kind="added",
                new_page=new_block.page,
                new_bbox=new_block.bbox,
                new_text=new_block.text,
                similarity=round(best_similarity, 4),
            )
        )

    for index, is_used in enumerate(used):
        if not is_used:
            old_block = old_blocks[index]
            changes.append(
                VersionChange(
                    kind="removed",
                    old_page=old_block.page,
                    old_bbox=old_block.bbox,
                    old_text=old_block.text,
                    similarity=0.0,
                )
            )
    return changes


def _format_changes(changes: list[VersionChange]) -> str:
    lines: list[str] = []
    for index, change in enumerate(changes, start=1):
        locations = []
        if change.new_page is not None:
            locations.append(f"新版 p.{change.new_page}")
        if change.old_page is not None:
            locations.append(f"旧版 p.{change.old_page}")
        text = change.new_text or change.old_text or ""
        snippet = " ".join(text.split())[:SUMMARY_ITEM_CHARS]
        lines.append(
            f"{index}. [{_KIND_LABELS[change.kind]}] {'; '.join(locations)} :: {snippet}"
        )
    return "\n".join(lines)


def _fallback_summary(changes: list[VersionChange]) -> str:
    counts = Counter(change.kind for change in changes)
    lines = [
        "（自动生成的确定性摘要：未调用 LLM，或 LLM 输出未通过页码校验）",
        "",
        f"- 新增段落：{counts.get('added', 0)} 处",
        f"- 删除段落：{counts.get('removed', 0)} 处",
        f"- 改写段落：{counts.get('modified', 0)} 处",
        "",
    ]
    for change in changes[:5]:
        locations = []
        if change.new_page is not None:
            locations.append(f"[新版 p.{change.new_page}]")
        if change.old_page is not None:
            locations.append(f"[旧版 p.{change.old_page}]")
        snippet = " ".join((change.new_text or change.old_text or "").split())[:120]
        lines.append(f"- {_KIND_LABELS[change.kind]} {' '.join(locations)}：{snippet}")
    return "\n".join(lines)


def _summary_pages_valid(summary: str, changes: list[VersionChange]) -> bool:
    valid = {
        ("新版", change.new_page)
        for change in changes
        if change.new_page is not None
    } | {
        ("旧版", change.old_page)
        for change in changes
        if change.old_page is not None
    }
    for match in _PAGE_LABEL_RE.finditer(summary):
        if (match.group(1), int(match.group(2))) not in valid:
            return False
    pages = {page for _, page in valid}
    for match in _BARE_PAGE_RE.finditer(summary):
        if int(match.group(1)) not in pages:
            return False
    return True


async def summarize_diff(changes: list[VersionChange]) -> str:
    if not changes:
        return "两版正文段落高度一致，未检测到明确差异。"
    if not settings.llm_configured:
        return _fallback_summary(changes)
    user = (
        "以下是同一论文两个 arXiv 版本之间的段落差异清单"
        "（每条已标注页码，文本经过截断）：\n\n"
        + _format_changes(changes)
        + "\n\n请输出中文 Markdown 总结，要求：\n"
        "1. 按「新增 / 删除 / 改写」三个分组列出主要修订；\n"
        "2. 每条差异后用 [新版 p.X] 或 [旧版 p.Y] 标注页码，只能使用清单中出现的页码；\n"
        "3. 不得编造清单之外的差异；证据不足就写「未检测到明确差异」；\n"
        "4. 全文控制在 500 字以内。"
    )
    answer = await chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        max_tokens=SUMMARY_MAX_TOKENS,
    )
    if answer and _summary_pages_valid(answer, changes):
        return answer.strip()
    logger.warning("LLM summary failed page validation; using deterministic fallback")
    return _fallback_summary(changes)


def build_diff(new: Paper, old: Paper) -> VersionDiffResponse:
    return VersionDiffResponse(
        new_id=new.id,
        old_id=old.id,
        similarity=round(whole_similarity(new, old), 4),
        changes=align_paragraphs(new, old),
        summary="",
    )


async def diff_papers(new: Paper, old: Paper) -> VersionDiffResponse:
    response = build_diff(new, old)
    response.summary = await summarize_diff(response.changes)
    return response
