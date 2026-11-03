"""Executor tests: event order, placeholders, failure stops, answer passthrough."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.agent.executor import run_plan
from app.agent.router import AgentPlan, PlanStep
from app.agent.tools.base import Tool, ToolContext, ToolResult


class BuildArgs(BaseModel):
    paper_ids: list[str] = []


class SurveyArgs(BaseModel):
    graph_id: str = ""


class FakeBuildTool(Tool):
    name = "fake.build"
    description = "fake"
    args_model = BuildArgs

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        self.calls.append(args)
        return ToolResult(
            ok=True,
            summary="图谱已构建",
            data={"graph_id": "g1", "node_count": 3},
        )


class FakeSurveyTool(Tool):
    name = "fake.survey"
    description = "fake"
    args_model = SurveyArgs

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        self.calls.append(args)
        return ToolResult(
            ok=True,
            summary="综述完成",
            data={"markdown": "# 综述"},
            citations=[{"paper_id": "p1", "page": 2}],
        )


class FakeFailTool(Tool):
    name = "fake.fail"
    description = "fake"
    args_model = BuildArgs

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        self.calls.append(args)
        return ToolResult(ok=False, summary="工具失败：模拟错误")


class FakeAnswerTool(Tool):
    name = "library.answer"
    description = "fake"
    args_model = BuildArgs

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        self.calls.append(args)
        return ToolResult(
            ok=True,
            summary="回答完成",
            data={"answer": "最终答案", "model": "test-model", "grounded": True},
            citations=[{"paper_id": "p1", "page": 5, "block_id": "b1", "quote": "x"}],
        )


@pytest.fixture
def registry(monkeypatch):
    from app.agent.tools import REGISTRY

    build = FakeBuildTool()
    survey = FakeSurveyTool()
    fail = FakeFailTool()
    answer = FakeAnswerTool()
    monkeypatch.setitem(REGISTRY, build.name, build)
    monkeypatch.setitem(REGISTRY, survey.name, survey)
    monkeypatch.setitem(REGISTRY, fail.name, fail)
    monkeypatch.setitem(REGISTRY, answer.name, answer)
    return {"build": build, "survey": survey, "fail": fail, "answer": answer}


async def _no_chat(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_placeholder_resolution_and_event_order(registry, monkeypatch) -> None:
    monkeypatch.setattr("app.agent.executor.chat", _no_chat)
    events: list[tuple[str, dict]] = []

    async def emit(event: str, data: dict) -> None:
        events.append((event, data))

    plan = AgentPlan(
        intent="构建并综述",
        steps=[
            PlanStep(tool="fake.build", args={"paper_ids": ["p1"]}),
            PlanStep(tool="fake.survey", args={"graph_id": "$graph_id"}),
        ],
    )
    result = await run_plan(plan, ToolContext(question="生成综述"), emit)

    assert registry["survey"].calls[0].graph_id == "g1"
    assert [event for event, _ in events] == [
        "tool_start",
        "tool_result",
        "tool_start",
        "tool_result",
    ]
    assert result.citations == [{"paper_id": "p1", "page": 2}]
    assert any("fake.build" in line for line in result.trace)
    assert result.answer  # deterministic joined fallback
    assert result.model == "extractive-fallback"


@pytest.mark.asyncio
async def test_failure_stops_following_steps(registry, monkeypatch) -> None:
    monkeypatch.setattr("app.agent.executor.chat", _no_chat)
    events: list[tuple[str, dict]] = []

    async def emit(event: str, data: dict) -> None:
        events.append((event, data))

    plan = AgentPlan(
        intent="先失败",
        steps=[
            PlanStep(tool="fake.fail", args={}),
            PlanStep(tool="fake.build", args={}),
        ],
    )
    result = await run_plan(plan, ToolContext(question="任务"), emit)

    assert registry["build"].calls == []
    assert not result.citations
    assert "任务未完成" in result.answer
    assert len(events) == 2  # one start + one result


@pytest.mark.asyncio
async def test_library_answer_passthrough(registry, monkeypatch) -> None:
    monkeypatch.setattr("app.agent.executor.chat", _no_chat)
    plan = AgentPlan(
        intent="直接回答",
        steps=[PlanStep(tool="library.answer", args={"paper_ids": []})],
    )

    async def emit(_event: str, _data: dict) -> None:
        return None

    result = await run_plan(plan, ToolContext(question="问题"), emit)

    assert result.answer == "最终答案"
    assert result.model == "test-model"
    assert result.grounded is True
    assert len(result.citations) == 1


@pytest.mark.asyncio
async def test_invalid_args_are_reported(registry, monkeypatch) -> None:
    monkeypatch.setattr("app.agent.executor.chat", _no_chat)
    events: list[tuple[str, dict]] = []

    async def emit(event: str, data: dict) -> None:
        events.append((event, data))

    plan = AgentPlan(
        intent="坏参数",
        steps=[PlanStep(tool="fake.build", args={"paper_ids": "not-a-list"})],
    )
    result = await run_plan(plan, ToolContext(question="任务"), emit)

    assert registry["build"].calls == []
    assert events[-1][0] == "tool_result"
    assert events[-1][1]["ok"] is False
    assert "参数校验失败" in result.answer
