"""Tool contract shared by every agent tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool = True
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class ToolContext(BaseModel):
    question: str = ""
    paper_ids: list[str] = Field(default_factory=list)
    user_language: str = "zh"
    history: list[str] = Field(default_factory=list)


class Tool(ABC):
    """A registered agent tool: a pydantic args model plus an async runner."""

    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        """Execute the tool; never raise — report failures via ToolResult.ok."""
