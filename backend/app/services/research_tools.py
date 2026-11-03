"""Survey and future-work helpers shared by the graph API and agent tools."""

from __future__ import annotations

import re

from app.core.config import settings
from app.models.schemas import BlockKind, FutureWorkItem, GraphResponse
from app.services.dedup import jaccard, normalize, shingles
from app.services.llm import chat
from app.store import paper_store

_FUTURE_HEADING = re.compile(
    r"future work|future direction|future research|open problems", re.I
)


def future_work_items(graph: GraphResponse, limit: int = 20) -> list[FutureWorkItem]:
    items: list[FutureWorkItem] = []
    for node in graph.nodes:
        paper = paper_store.get(node.id)
        if paper is None:
            continue
        blocks = paper.blocks
        for index, block in enumerate(blocks):
            if (
                block.kind != BlockKind.heading
                or not _FUTURE_HEADING.search(block.text)
            ):
                continue
            evidence: list[str] = []
            for follow in blocks[index + 1 : index + 4]:
                if follow.kind == BlockKind.heading:
                    break
                evidence.append(follow.text.strip())
                if sum(len(part) for part in evidence) > 500:
                    break
            text = " ".join(evidence).strip()
            if len(text) < 60:
                continue
            items.append(
                FutureWorkItem(
                    idea=block.text.strip()[:120],
                    paper_id=paper.id,
                    paper_title=paper.title,
                    year=node.year,
                    page=block.page,
                    evidence=text[:800],
                )
            )
    kept: list[FutureWorkItem] = []
    seen: list[set[tuple[str, ...]]] = []
    for item in sorted(items, key=lambda value: value.year or 0, reverse=True):
        signature = shingles(normalize(item.evidence))
        if any(jaccard(signature, prior) >= 0.7 for prior in seen):
            continue
        kept.append(item)
        seen.append(signature)
    return kept[:limit]


def abstract_for(node_id: str, title: str) -> str:
    paper = paper_store.get(node_id)
    if paper is None:
        wanted = title.strip().lower()
        paper = next(
            (
                item
                for item in paper_store.list()
                if (item.title or "").strip().lower() == wanted
            ),
            None,
        )
    if paper is None:
        return ""
    for block in paper.blocks[:8]:
        if block.kind.value == "paragraph" and len(block.text) >= 80:
            return " ".join(block.text.split())[:500]
    return ""


async def llm_survey(graph: GraphResponse) -> str | None:
    if not settings.llm_configured or not graph.nodes:
        return None
    by_id = {node.id: node for node in graph.nodes}
    ranked = sorted(
        graph.nodes, key=lambda node: (node.centrality, node.citations), reverse=True
    )
    papers = []
    for node in ranked[:10]:
        abstract = abstract_for(node.id, node.title)
        papers.append(
            f"- {node.title} ({node.year or 'n.d.'})；被引 {node.citations}；"
            f"中心度 {node.centrality}"
            + (f"\n  摘要/开头：{abstract}" if abstract else "")
        )
    edges = [
        f"- {by_id[edge.source].title} → {by_id[edge.target].title}"
        for edge in graph.edges
        if edge.source in by_id and edge.target in by_id
    ][:40]
    prompt = (
        "你是学术综述助手。仅依据下面给出的图谱节点、引用边和论文摘要写作，"
        "不得编造论文、年份、数据或结论；证据不足时直接写“证据不足”。\n"
        f"图谱摘要：{graph.summary}\n\n核心节点：\n" + "\n".join(papers)
        + "\n\n引用边：\n" + ("\n".join(edges) if edges else "（无）")
        + "\n\n请输出 Markdown 综述，包含：领域概览、研究脉络（按时间与引用方向）、"
        "基石工作、争议与空白、未来方向。每个论断后用[论文标题]标注来源，"
        "只用上面出现过的标题。不要输出 JSON。"
    )
    raw = await chat(
        [{"role": "user", "content": prompt}],
        temperature=0.35,
        max_tokens=2200,
    )
    return raw.strip() if raw and raw.strip() else None
