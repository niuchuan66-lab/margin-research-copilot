"""Agent tool registry: name → Tool instance."""

from __future__ import annotations

from app.agent.tools.arxiv import ArxivDownloadTool, ArxivSearchTool
from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.agent.tools.graph import (
    GraphBuildTool,
    GraphFutureWorkTool,
    GraphSurveyTool,
)
from app.agent.tools.library import LibraryAnswerTool, LibrarySearchTool
from app.agent.tools.python_exec import PythonExecTool
from app.agent.tools.writing import WritingChartTool, WritingOutlineTool

__all__ = ["Tool", "ToolContext", "ToolResult", "REGISTRY", "get_tool", "describe_tools"]

REGISTRY: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        LibrarySearchTool(),
        LibraryAnswerTool(),
        ArxivSearchTool(),
        ArxivDownloadTool(),
        GraphBuildTool(),
        GraphSurveyTool(),
        GraphFutureWorkTool(),
        WritingOutlineTool(),
        WritingChartTool(),
        PythonExecTool(),
    )
}


def get_tool(name: str) -> Tool | None:
    return REGISTRY.get(name)


def describe_tools() -> str:
    return "\n".join(
        f"- {tool.name}: {tool.description}" for tool in REGISTRY.values()
    )
