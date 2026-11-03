"""Intent routing for the agent: rule-first, LLM planner as fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent.tools import REGISTRY, describe_tools
from app.services.llm import chat
from app.store import paper_store

logger = logging.getLogger(__name__)

_ARXIV_ID_RE = re.compile(
    r"\b(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)\b",
    re.I,
)
_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)
_NUMBERS_RE = re.compile(r"-?\d+(?:\.\d+)?")
_MAX_PLAN_STEPS = 3


class PlanStep(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    intent: str = ""
    steps: list[PlanStep] = Field(default_factory=list)


def _fallback_plan(question: str, paper_ids: list[str]) -> AgentPlan:
    return AgentPlan(
        intent="直接回答",
        steps=[
            PlanStep(
                tool="library.answer",
                args={"question": question, "paper_ids": paper_ids},
            )
        ],
    )


def _rule_plan(question: str, paper_ids: list[str]) -> AgentPlan | None:
    text = question.lower()

    if ("下载" in text or "入库" in text or "download" in text) and (
        "arxiv" in text or _ARXIV_ID_RE.search(question) or "论文" in question
    ):
        match = _ARXIV_ID_RE.search(question)
        if match:
            return AgentPlan(
                intent="下载 arXiv 论文并入库",
                steps=[
                    PlanStep(tool="arxiv.download", args={"arxiv_id": match.group(1)})
                ],
            )
        title = re.sub(r"^\S*arxiv\S*\s*", "", _strip_leading_words(question), flags=re.I)
        return AgentPlan(
            intent="下载 arXiv 论文并入库",
            steps=[
                PlanStep(
                    tool="arxiv.download",
                    args={"title": title.strip()[:200] or question[:200]},
                )
            ],
        )

    if (
        ("搜索" in text or "搜" in text or "找" in text or "推荐" in text or "arxiv" in text)
        and ("篇" in text or "arxiv" in text or "最新" in text)
        and "库" not in text
    ):
        query = _strip_leading_words(question)
        query = re.sub(r"^\S*arxiv\S*\s*", "", query, flags=re.I).strip()
        return AgentPlan(
            intent="arXiv 检索",
            steps=[
                PlanStep(
                    tool="arxiv.search",
                    args={"query": query[:300] or question[:300], "limit": 5},
                )
            ],
        )

    if re.search(r"画图|图表|雷达图|折线图|柱状图|csv|chart|画成", text):
        csv_text = _extract_csv(question)
        if csv_text is None:
            return None
        chart_type = "radar" if "雷达" in question else ("bar" if "柱状" in question else "line")
        return AgentPlan(
            intent="CSV 数据可视化",
            steps=[
                PlanStep(
                    tool="writing.chart",
                    args={
                        "csv": csv_text,
                        "title": _chart_title(question),
                        "chart_type": chart_type,
                    },
                )
            ],
        )

    if re.search(r"对比|差异|版本", text) or re.search(
        r"\b(compare|diff|version)\b", text
    ):
        return AgentPlan(
            intent="多版本对比问答",
            steps=[
                PlanStep(
                    tool="library.answer",
                    args={"question": question, "paper_ids": paper_ids},
                )
            ],
        )

    if "大纲" in text or "outline" in text or "章节安排" in text:
        return AgentPlan(
            intent="生成论文大纲",
            steps=[
                PlanStep(
                    tool="writing.outline",
                    args={"idea": question, "paper_ids": paper_ids},
                )
            ],
        )

    if "综述" in text or "脉络" in text or "领域概览" in text or re.search(
        r"\bsurvey\b", text
    ):
        return AgentPlan(
            intent="构建图谱并生成综述",
            steps=[
                PlanStep(tool="graph.build", args={"paper_ids": paper_ids}),
                PlanStep(tool="graph.survey", args={"graph_id": "$graph_id"}),
            ],
        )
    if "未来方向" in text or "future work" in text or "研究空白" in text:
        return AgentPlan(
            intent="构建图谱并提取未来方向",
            steps=[
                PlanStep(tool="graph.build", args={"paper_ids": paper_ids}),
                PlanStep(tool="graph.future_work", args={"graph_id": "$graph_id"}),
            ],
        )
    if "图谱" in text or "引用网络" in text or "基石" in text or re.search(
        r"\bgraph\b", text
    ):
        return AgentPlan(
            intent="构建引用图谱",
            steps=[PlanStep(tool="graph.build", args={"paper_ids": paper_ids})],
        )

    code = _extract_code(question)
    if code is not None:
        return AgentPlan(
            intent="Python 计算",
            steps=[PlanStep(tool="python.exec", args={"code": code})],
        )
    numbers = _NUMBERS_RE.findall(question)
    if len(numbers) >= 3 and re.search(r"算|计算|均值|平均|求和|方差|标准差", text):
        values = ", ".join(numbers[:50])
        operation = "statistics.mean" if "均值" in text or "平均" in text else "sum"
        code = f"import statistics\nprint({operation}([{values}]))"
        if operation == "sum":
            code = f"print(sum([{values}]))"
        return AgentPlan(
            intent="Python 计算",
            steps=[PlanStep(tool="python.exec", args={"code": code})],
        )

    return None


def _strip_leading_words(question: str) -> str:
    text = question.strip()
    for prefix in ("请帮我", "帮我", "请", "我想", "我要", "麻烦"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    text = re.sub(r"^(下载|搜索|检索|找|查)\s*", "", text).strip()
    return re.sub(r"^\d+\s*[篇本个]\s*", "", text).strip()


def _extract_csv(question: str) -> str | None:
    fence = re.search(r"```(?:csv)?\s*\n(.*?)```", question, re.S)
    if fence:
        return fence.group(1).strip()
    lines = [line.strip() for line in question.splitlines() if line.strip()]
    candidates = [line for line in lines if line.count(",") >= 1]
    if len(candidates) >= 2 and any(
        re.search(r"\d", line) for line in candidates
    ) and any(re.search(r"[A-Za-z\u4e00-\u9fff]", line) for line in candidates):
        return "\n".join(candidates[:50])
    return None


def _chart_title(question: str) -> str:
    text = _strip_leading_words(question)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"(画成|画一个|生成|做成|转成).*", "", text).strip()
    title = re.split(r"[，。；;]| 说明", text)[0].strip()[:50]
    return title or "对话数据"


def _extract_code(question: str) -> str | None:
    fence = _CODE_FENCE_RE.search(question)
    if fence:
        code = fence.group(1).strip()
        return code[:20000] if code else None
    if "运行这段代码" in question or "执行这段代码" in question:
        rest = re.split(r"(运行|执行)这段代码", question)[-1].strip()
        rest = rest.lstrip("：:").strip()
        return rest[:20000] if rest else None
    return None


def _planner_prompt(question: str, paper_ids: list[str]) -> str:
    library = ""
    papers = [
        paper_store.get(paper_id)
        for paper_id in paper_ids
        if paper_store.get(paper_id) is not None
    ]
    if not papers:
        papers = paper_store.list()[:6]
    for paper in papers:
        abstract = " ".join(
            " ".join(block.text.split())
            for block in paper.blocks[:4]
            if block.kind.value == "paragraph"
        )[:200]
        library += f"- {paper.title or paper.filename}（id={paper.id}）{abstract}\n"
    return (
        "你是科研助手的路由器。根据用户问题，从下面的工具中选择 1–3 步完成目标，"
        "输出严格 JSON，不要解释。\n\n"
        "工具清单：\n"
        f"{describe_tools()}\n\n"
        "参数规则：library.answer 的 question 原样传用户问题；"
        "graph.survey / graph.future_work 的 graph_id 用 \"$graph_id\"（上一步产物）；"
        "writing.chart 需要 csv 文本、title、chart_type（line/bar/radar）；"
        "python.exec 需要 code；arxiv.download 需要 arxiv_id 或 title。\n\n"
        "JSON 格式：{\"intent\":\"一句话意图\",\"steps\":[{\"tool\":\"工具名\","
        "\"args\":{...}}]}，steps 最多 3 步。\n\n"
        f"本地论文库（只有标题与开头，禁止把全文放进计划）：\n{library or '（空）'}\n\n"
        f"用户问题：{question[:1000]}"
    )


async def _llm_plan(question: str, paper_ids: list[str]) -> AgentPlan | None:
    raw = await chat(
        [{"role": "user", "content": _planner_prompt(question, paper_ids)}],
        temperature=0.1,
        max_tokens=600,
    )
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    steps_data = payload.get("steps")
    if not isinstance(steps_data, list) or not steps_data:
        return None
    steps: list[PlanStep] = []
    for item in steps_data[: _MAX_PLAN_STEPS]:
        if not isinstance(item, dict):
            return None
        tool_name = str(item.get("tool") or "")
        tool = REGISTRY.get(tool_name)
        if tool is None:
            logger.info("Planner returned unknown tool %r; falling back", tool_name)
            return None
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        try:
            tool.args_model.model_validate(args)
        except ValidationError as exc:
            logger.info("Planner args invalid for %s: %s", tool_name, exc)
            return None
        steps.append(PlanStep(tool=tool_name, args=args))
    return AgentPlan(intent=str(payload.get("intent") or "")[:200], steps=steps)


async def plan_request(question: str, paper_ids: list[str]) -> AgentPlan:
    """Rule-first routing with an LLM planner fallback and a safe default."""

    plan = _rule_plan(question, paper_ids)
    if plan is not None:
        return plan
    try:
        plan = await _llm_plan(question, paper_ids)
        if plan is not None:
            return plan
    except Exception as exc:
        logger.info("LLM planner failed (%s); using library.answer", exc)
    return _fallback_plan(question, paper_ids)
