from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    FutureWorkResponse,
    GraphBuildRequest,
    GraphResponse,
    SurveyResponse,
)
from app.services.graph_service import build_citation_graph, get_graph
from app.services.research_tools import future_work_items, llm_survey
from app.store import paper_store

router = APIRouter(prefix="/graph", tags=["graph"])


@router.post("/build", response_model=GraphResponse)
def build(payload: GraphBuildRequest) -> GraphResponse:
    if payload.paper_ids:
        papers = [paper_store.get(paper_id) for paper_id in payload.paper_ids]
        papers = [paper for paper in papers if paper is not None]
    else:
        papers = paper_store.list()
    if not papers:
        raise HTTPException(status_code=400, detail="至少需要一篇论文")
    return build_citation_graph(papers)


@router.get("/{graph_id}", response_model=GraphResponse)
def read(graph_id: str) -> GraphResponse:
    graph = get_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="图谱不存在")
    return graph


@router.post("/{graph_id}/survey", response_model=SurveyResponse)
async def survey(graph_id: str) -> SurveyResponse:
    graph = get_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="图谱不存在")
    markdown = await llm_survey(graph)
    if markdown:
        return SurveyResponse(graph_id=graph_id, markdown=markdown)
    cornerstones = [node for node in graph.nodes if node.is_cornerstone]
    lines = [
        "# 领域综述草稿",
        "",
        graph.summary,
        "",
        "## 基石论文",
    ]
    if cornerstones:
        lines.extend(
            f"- {node.title}（{node.year or '年份未明确'}；"
            f"被引 {node.citations}；中心度 {node.centrality}）"
            for node in cornerstones[:10]
        )
    else:
        lines.append("- 当前图谱还没有足够的引用边，先补充文献或检查 References 解析。")
    lines.extend(
        [
            "",
            "## 研究脉络",
            "按引用方向从基石论文向外展开；每一条结论都需要回到原文核对。",
            "",
            "## 待验证的未来方向",
            "- 从各论文 Future Work 段落抽取候选方向，并用后续论文摘要做新颖性过滤。",
        ]
    )
    return SurveyResponse(graph_id=graph_id, markdown="\n".join(lines))


@router.post("/{graph_id}/future-work", response_model=FutureWorkResponse)
def future_work(graph_id: str) -> FutureWorkResponse:
    graph = get_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="图谱不存在")
    return FutureWorkResponse(
        graph_id=graph_id, items=future_work_items(graph)
    )
