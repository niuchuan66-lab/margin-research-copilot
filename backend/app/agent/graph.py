"""LangGraph orchestration with a sequential fallback.

The graph is deliberately small: plan → retrieve → answer → verify.
It is the seam where a richer planner / multi-agent router can be added
without changing the API contract.
"""

from __future__ import annotations

import logging

from app.agent.state import AgentState
from app.core.config import settings
from app.models.schemas import AnswerResponse
from app.services.indexing import get_index
from app.services.qa import answer_from_hits, expand_hits

logger = logging.getLogger(__name__)


async def _plan(state: AgentState) -> AgentState:
    return {
        **state,
        "plan": ["retrieve", "answer", "verify_citations"],
        "trace": [*state.get("trace", []), "plan: LangGraph plan→retrieve→answer→verify"],
    }


async def _retrieve(state: AgentState) -> AgentState:
    hits = expand_hits(
        get_index().search(
            state["question"],
            paper_ids=state.get("paper_ids") or None,
            top_k=state.get("top_k", 6),
        )
    )
    return {
        **state,
        "hits": hits,
        "trace": [*state.get("trace", []), f"retrieve: {len(hits)} 个片段"],
    }


async def _answer(state: AgentState) -> AgentState:
    response = await answer_from_hits(
        state["question"], state.get("hits", [])
    )
    return {
        **state,
        "answer": response.answer,
        "citations": [citation.model_dump() for citation in response.citations],
        "model": response.model,
        "trace": [*state.get("trace", []), *response.trace],
    }


async def _verify(state: AgentState) -> AgentState:
    hits = state.get("hits", [])
    source_text = "\n".join(chunk.text for chunk, _score in hits)
    kept = []
    for citation in state.get("citations", []):
        quote = str(citation.get("quote", "")).strip()
        if not quote or quote[:80] in source_text:
            kept.append(citation)
    trace = [*state.get("trace", []), f"verify: {len(kept)} 条引用通过原文校验"]
    return {**state, "citations": kept, "trace": trace}


def _build_langgraph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(AgentState)
    graph.add_node("plan", _plan)
    graph.add_node("retrieve", _retrieve)
    graph.add_node("answer", _answer)
    graph.add_node("verify", _verify)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


async def run_agent(
    question: str,
    paper_ids: list[str] | None = None,
    top_k: int = 6,
) -> AnswerResponse:
    state: AgentState = {
        "question": question,
        "paper_ids": paper_ids or [],
        "top_k": top_k,
        "trace": [],
    }
    if settings.app_env != "test":
        try:
            compiled = _build_langgraph()
            result = await compiled.ainvoke(state)
            return AnswerResponse(
                answer=result.get("answer", ""),
                citations=result.get("citations", []),
                trace=result.get("trace", []),
                model=result.get("model", settings.llm_model),
                grounded=bool(result.get("citations")),
            )
        except Exception as exc:
            logger.info("LangGraph unavailable (%s); using sequential fallback", exc)

    state = await _plan(state)
    state = await _retrieve(state)
    state = await _answer(state)
    state = await _verify(state)
    return AnswerResponse(
        answer=state.get("answer", ""),
        citations=state.get("citations", []),
        trace=state.get("trace", []),
        model=state.get("model", "extractive-fallback"),
        grounded=bool(state.get("citations")),
    )
