"""Plan executor: runs tool steps in order, emits progress, composes the answer."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent.router import AgentPlan
from app.agent.tools import REGISTRY
from app.agent.tools.base import ToolContext, ToolResult
from app.core.config import settings
from app.services.llm import chat

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"^\$([A-Za-z_][\w.]*)$")
_SUMMARY_SYSTEM_PROMPT = (
    "你是 Margin 科研助手的汇总模块。仅依据下面给出的工具执行结果回答用户问题，"
    "不要编造工具没有返回的数据、数值或文献；如果工具失败，直接说明失败原因。"
    "用中文简洁作答，可用短列表。"
)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class AgentRunResult(BaseModel):
    answer: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    model: str = "extractive-fallback"
    grounded: bool = False


async def run_plan(
    plan: AgentPlan, context: ToolContext, emit: Emit
) -> AgentRunResult:
    trace = [f"plan: {plan.intent or '（未命名）'}（{len(plan.steps)} 步）"]
    citations: list[dict[str, Any]] = []
    variables: dict[str, Any] = {}
    history: list[str] = []
    last_result: ToolResult | None = None

    for step in plan.steps:
        tool = REGISTRY.get(step.tool)
        if tool is None:
            message = f"未知工具：{step.tool}"
            trace.append(f"tool: {step.tool} → {message}")
            await emit(
                "tool_result", {"tool": step.tool, "ok": False, "summary": message}
            )
            break
        args_data = _resolve_args(step.args, variables)
        await emit("tool_start", {"tool": step.tool, "args": args_data})
        trace.append(f"tool: {step.tool} 开始")
        try:
            validated = tool.args_model.model_validate(args_data)
        except ValidationError as exc:
            message = f"参数校验失败：{exc.errors()[:1]}"
            await emit(
                "tool_result", {"tool": step.tool, "ok": False, "summary": message}
            )
            trace.append(f"tool: {step.tool} → {message}")
            history.append(f"[{step.tool}] {message}")
            break
        try:
            result = await tool.run(validated, context)
        except Exception as exc:  # tools should not raise; keep the loop alive
            logger.exception("Tool %s crashed", step.tool)
            result = ToolResult(ok=False, summary=f"工具执行异常：{exc}")
        last_result = result
        summary = (result.summary or "").strip()[:240]
        await emit(
            "tool_result",
            {
                "tool": step.tool,
                "ok": result.ok,
                "summary": summary,
                "artifacts": result.artifacts,
            },
        )
        trace.append(f"tool: {step.tool} → {summary}")
        history.append(f"[{step.tool}] {summary}")
        citations.extend(result.citations)
        variables.update(result.data)
        if not result.ok:
            break

    answer, model, grounded = await _compose_answer(
        context.question, history, last_result, citations
    )
    trace.append(f"answer: {model}")
    return AgentRunResult(
        answer=answer,
        citations=citations,
        trace=trace,
        model=model,
        grounded=grounded,
    )


async def _compose_answer(
    question: str,
    history: list[str],
    last_result: ToolResult | None,
    citations: list[dict[str, Any]],
) -> tuple[str, str, bool]:
    if last_result is not None and last_result.ok and "answer" in last_result.data:
        answer = str(last_result.data.get("answer") or "")
        model = str(last_result.data.get("model") or settings.llm_model)
        grounded = bool(last_result.data.get("grounded"))
        return answer, model, grounded
    if last_result is None:
        if history:
            return f"任务未完成：{history[-1]}", "extractive-fallback", False
        return "没有执行任何工具，无法完成任务。", "extractive-fallback", False
    if settings.llm_configured:
        summary = await chat(
            [
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"用户问题：{question}\n\n工具执行结果：\n"
                        + "\n".join(history[:20])
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=900,
        )
        if summary:
            return summary.strip(), settings.llm_model, bool(citations)
    if not last_result.ok:
        return (
            f"任务未完成：{last_result.summary}",
            "extractive-fallback",
            False,
        )
    return (
        "已完成以下步骤：\n" + "\n".join(f"- {item}" for item in history),
        "extractive-fallback",
        bool(citations),
    )


def _resolve_args(args: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            match = _PLACEHOLDER_RE.match(value)
            if match:
                resolved[key] = _dotted_get(variables, match.group(1))
                continue
        resolved[key] = value
    return resolved


def _dotted_get(variables: dict[str, Any], path: str) -> Any:
    value: Any = variables
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value
