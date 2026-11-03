"""Writing-assistant tools: outline generation and CSV-to-chart."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.services.writing import build_outline_llm, csv_to_chart_llm
from app.store import paper_store

logger = logging.getLogger(__name__)


class WritingOutlineArgs(BaseModel):
    idea: str = Field(min_length=4, max_length=4000)
    paper_ids: list[str] = Field(default_factory=list)
    language: Literal["zh", "en"] = "zh"


class WritingChartArgs(BaseModel):
    csv: str = Field(min_length=3, max_length=20000)
    title: str = Field(default="Figure", max_length=200)
    chart_type: Literal["line", "bar", "radar"] = "line"


class WritingOutlineTool(Tool):
    name = "writing.outline"
    description = "基于研究想法与本地文献库生成论文章节大纲，参考文献只来自库内。"
    args_model = WritingOutlineArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        outline_args: WritingOutlineArgs = args  # type: ignore[assignment]
        if outline_args.paper_ids:
            papers = [paper_store.get(paper_id) for paper_id in outline_args.paper_ids]
            papers = [paper for paper in papers if paper is not None]
        elif context.paper_ids:
            papers = [
                paper_store.get(paper_id) for paper_id in context.paper_ids
            ]
            papers = [paper for paper in papers if paper is not None]
        else:
            papers = [
                paper
                for paper in paper_store.list()
                if paper.status.value == "ready"
            ][:8]
        try:
            outline = await build_outline_llm(
                outline_args.idea, papers, outline_args.language
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("writing.outline failed: %s", exc)
            return ToolResult(ok=False, summary=f"大纲生成失败：{exc}")
        return ToolResult(
            ok=True,
            summary=f"大纲已生成：{outline.title[:60]}，共 {len(outline.sections)} 节。",
            data={
                "title": outline.title,
                "sections": [
                    {
                        "heading": section.heading,
                        "intent": section.intent,
                        "citation_count": len(section.citations),
                    }
                    for section in outline.sections
                ],
                "reference_count": len(outline.references),
            },
        )


class WritingChartTool(Tool):
    name = "writing.chart"
    description = "把 CSV 数据转成 ECharts 折线/柱状/雷达图配置与图注。"
    args_model = WritingChartArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        chart_args: WritingChartArgs = args  # type: ignore[assignment]
        try:
            chart = await csv_to_chart_llm(
                chart_args.csv, chart_args.title, chart_args.chart_type
            )
        except ValueError as exc:
            return ToolResult(ok=False, summary=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("writing.chart failed: %s", exc)
            return ToolResult(ok=False, summary=f"图表生成失败：{exc}")
        return ToolResult(
            ok=True,
            summary=f"已生成 {chart_args.chart_type} 图：{chart.caption[:100]}",
            data={
                "option": chart.option,
                "caption": chart.caption,
                "columns": chart.columns,
                "rows": chart.rows,
                "chart_type": chart_args.chart_type,
            },
        )
