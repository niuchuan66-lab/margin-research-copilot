"""Citation-graph tools: build, survey and future-work extraction."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.services.graph_service import build_citation_graph, get_graph
from app.services.research_tools import future_work_items, llm_survey
from app.store import paper_store

logger = logging.getLogger(__name__)


class GraphBuildArgs(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


class GraphIdArgs(BaseModel):
    graph_id: str = Field(min_length=1, max_length=64)


def _resolve_papers(paper_ids: list[str]):
    if paper_ids:
        papers = [paper_store.get(paper_id) for paper_id in paper_ids]
        return [paper for paper in papers if paper is not None]
    return paper_store.list()


class GraphBuildTool(Tool):
    name = "graph.build"
    description = "根据本地论文的参考文献构建引用图谱，返回 graph_id 与基石论文。"
    args_model = GraphBuildArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        build_args: GraphBuildArgs = args  # type: ignore[assignment]
        papers = _resolve_papers(build_args.paper_ids or context.paper_ids)
        if not papers:
            return ToolResult(ok=False, summary="至少需要一篇论文才能构建图谱。")
        try:
            graph = build_citation_graph(papers)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("graph.build failed: %s", exc)
            return ToolResult(ok=False, summary=f"图谱构建失败：{exc}")
        return ToolResult(
            ok=True,
            summary=f"图谱已构建：{graph.summary}",
            data={
                "graph_id": graph.graph_id,
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "summary": graph.summary,
            },
        )


class GraphSurveyTool(Tool):
    name = "graph.survey"
    description = "基于已构建的引用图谱生成领域综述草稿（Markdown）。"
    args_model = GraphIdArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        survey_args: GraphIdArgs = args  # type: ignore[assignment]
        graph = get_graph(survey_args.graph_id)
        if graph is None:
            return ToolResult(ok=False, summary="图谱不存在，请先 graph.build。")
        markdown = await llm_survey(graph)
        if not markdown:
            markdown = graph.summary
            return ToolResult(
                ok=True,
                summary="未配置 LLM，返回图谱摘要作为回退。",
                data={"graph_id": graph.graph_id, "markdown": markdown},
            )
        return ToolResult(
            ok=True,
            summary=f"综述草稿 {len(markdown)} 字。",
            data={"graph_id": graph.graph_id, "markdown": markdown},
        )


class GraphFutureWorkTool(Tool):
    name = "graph.future_work"
    description = "从图谱各论文的 Future Work 段落提取并合并未来研究方向。"
    args_model = GraphIdArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        work_args: GraphIdArgs = args  # type: ignore[assignment]
        graph = get_graph(work_args.graph_id)
        if graph is None:
            return ToolResult(ok=False, summary="图谱不存在，请先 graph.build。")
        items = future_work_items(graph)
        if not items:
            return ToolResult(
                ok=True,
                summary="没有提取到明确的未来方向段落。",
                data={"graph_id": graph.graph_id, "items": []},
            )
        ideas = "；".join(item.idea[:60] for item in items[:5])
        return ToolResult(
            ok=True,
            summary=f"提取到 {len(items)} 个方向：{ideas}",
            data={
                "graph_id": graph.graph_id,
                "items": [item.model_dump() for item in items],
            },
        )
