"""Routing tests for the tool-calling agent (plan doc section 7.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.router import _rule_plan, plan_request
from app.models.schemas import AgentRunRequest

CSV_QUESTION = """把这段 CSV 画成雷达图
model,accuracy,speed
A,0.81,120
B,0.85,110
C,0.88,95
"""


async def _fallback_plan(question: str, paper_ids: list[str]):
    return await plan_request(question, paper_ids)


@pytest.mark.asyncio
async def test_factual_question_falls_back_to_answer(monkeypatch) -> None:
    async def no_chat(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.agent.router.chat", no_chat)
    plan = await plan_request("训练用了多少块 GPU？", ["p1"])
    assert plan.steps[0].tool == "library.answer"
    assert plan.steps[0].args["question"] == "训练用了多少块 GPU？"
    assert plan.steps[0].args["paper_ids"] == ["p1"]


def test_multi_paper_comparison_routes_to_answer() -> None:
    plan = _rule_plan("这两篇论文的方法有什么差异？", ["p1", "p2"])
    assert plan is not None
    assert plan.steps[0].tool == "library.answer"
    assert plan.steps[0].args["paper_ids"] == ["p1", "p2"]


def test_arxiv_download_rule() -> None:
    plan = _rule_plan("下载 arXiv 1706.03762 并入库", [])
    assert plan is not None
    assert plan.steps[0].tool == "arxiv.download"
    assert plan.steps[0].args["arxiv_id"] == "1706.03762"


def test_arxiv_search_rule() -> None:
    plan = _rule_plan("找 5 篇 flash attention 论文", [])
    assert plan is not None
    assert plan.steps[0].tool == "arxiv.search"
    assert "flash attention" in plan.steps[0].args["query"]


def test_csv_radar_chart_rule() -> None:
    plan = _rule_plan(CSV_QUESTION, [])
    assert plan is not None
    assert plan.steps[0].tool == "writing.chart"
    assert plan.steps[0].args["chart_type"] == "radar"
    assert "model" in plan.steps[0].args["csv"]


def test_survey_rule_builds_graph_first() -> None:
    plan = _rule_plan("根据我的书架生成综述", ["p1", "p2"])
    assert plan is not None
    assert [step.tool for step in plan.steps] == ["graph.build", "graph.survey"]
    assert plan.steps[1].args["graph_id"] == "$graph_id"


def test_future_work_rule() -> None:
    plan = _rule_plan("提取未来方向", ["p1"])
    assert plan is not None
    assert [step.tool for step in plan.steps] == ["graph.build", "graph.future_work"]


def test_outline_rule() -> None:
    plan = _rule_plan("写一个大纲：低秩微调的综述", ["p1"])
    assert plan is not None
    assert plan.steps[0].tool == "writing.outline"
    assert plan.steps[0].args["paper_ids"] == ["p1"]


def test_mean_calculation_routes_to_python_exec() -> None:
    plan = _rule_plan("算一下这组数 1 2 3 4 5 的均值", [])
    assert plan is not None
    assert plan.steps[0].tool == "python.exec"
    assert "statistics.mean" in plan.steps[0].args["code"]


@pytest.mark.asyncio
async def test_fuzzy_question_falls_back_to_answer(monkeypatch) -> None:
    async def no_chat(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.agent.router.chat", no_chat)
    plan = await plan_request("嗯，帮我看看", [])
    assert plan.steps[0].tool == "library.answer"


def test_malicious_code_is_rejected() -> None:
    from app.agent.tools.python_exec import validate_code

    assert validate_code("import os\nos.system('dir')") is not None
    assert validate_code("open('secret.txt')") is not None
    assert validate_code("eval('1+1')") is not None
    assert validate_code("data = [1, 2, 3]\nprint(sum(data))") is None


def test_overlong_question_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        AgentRunRequest(question="x" * 4001)


@pytest.mark.asyncio
async def test_llm_planner_json_is_used(monkeypatch) -> None:
    async def fake_chat(*_args, **_kwargs):
        return (
            '{"intent": "搜索", "steps": [{"tool": "arxiv.search", '
            '"args": {"query": "diffusion", "limit": 3}}]}'
        )

    monkeypatch.setattr("app.agent.router.chat", fake_chat)
    plan = await plan_request("帮我了解下 diffusion 领域的最新研究", [])
    assert plan.steps[0].tool == "arxiv.search"
    assert plan.steps[0].args["query"] == "diffusion"


@pytest.mark.asyncio
async def test_planner_unknown_tool_falls_back(monkeypatch) -> None:
    async def fake_chat(*_args, **_kwargs):
        return '{"intent": "x", "steps": [{"tool": "hack.tool", "args": {}}]}'

    monkeypatch.setattr("app.agent.router.chat", fake_chat)
    plan = await plan_request("随便干点什么", [])
    assert plan.steps[0].tool == "library.answer"


@pytest.mark.asyncio
async def test_planner_bad_args_fall_back(monkeypatch) -> None:
    async def fake_chat(*_args, **_kwargs):
        return (
            '{"intent": "x", "steps": [{"tool": "library.answer", '
            '"args": {"question": 42}}]}'
        )

    monkeypatch.setattr("app.agent.router.chat", fake_chat)
    plan = await plan_request("随便干点什么", [])
    assert plan.steps[0].tool == "library.answer"
