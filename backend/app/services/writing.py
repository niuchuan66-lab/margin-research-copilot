"""Outline, diagram and CSV-to-chart helpers for the writing copilot."""

from __future__ import annotations

import csv
import io
import re

from app.models.schemas import (
    ChartResponse,
    Citation,
    FigureResponse,
    OutlineResponse,
    OutlineSection,
    Paper,
    Reference,
)

# Validated categorical order (see dataviz/references/palette.md). The first
# three slots pass all-pairs checks; later slots need direct labels or the table
# view that the writing page always renders.
CHART_COLORS = [
    "#2a78d6",
    "#eb6834",
    "#6250d6",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#1baf7a",
    "#e34948",
]

_SECTION_INTENTS_ZH = [
    ("摘要", "用 150–250 字概括问题、方法、主要结果与结论，不引入库外事实。"),
    ("引言", "说明研究问题、为什么重要、现有工作的缺口与本文贡献。"),
    ("相关工作", "按主题而非时间罗列库中文献，指出承袭与差异。"),
    ("方法", "描述方法、关键假设、变量与实现细节，引用对应原文。"),
    ("实验设计", "给出数据、基线、指标、超参数与可复现步骤。"),
    ("讨论", "解释结果、局限、失败情形与可能的替代解释。"),
    ("结论", "回到研究问题，总结贡献并给出下一步工作。"),
]

_SECTION_INTENTS_EN = [
    ("Abstract", "Summarize the problem, method, main results and conclusion in 150–250 words."),
    ("Introduction", "State the problem, why it matters, the gap and the contributions."),
    ("Related Work", "Organize library papers by theme and mark inheritance vs. difference."),
    ("Method", "Describe the method, assumptions, variables and implementation details."),
    ("Experiments", "Specify data, baselines, metrics, hyperparameters and reproduction steps."),
    ("Discussion", "Interpret results, limitations, failure modes and alternative explanations."),
    ("Conclusion", "Return to the research question and name the next step."),
]


def build_outline(idea: str, papers: list[Paper], language: str = "zh") -> OutlineResponse:
    sections_meta = _SECTION_INTENTS_ZH if language == "zh" else _SECTION_INTENTS_EN
    citations = [_citation_for_paper(paper) for paper in papers]
    sections = [
        OutlineSection(
            heading=heading,
            intent=intent,
            citations=citations[:6],
        )
        for heading, intent in sections_meta
    ]
    references: list[Reference] = []
    seen: set[str] = set()
    for paper in papers:
        if paper.title and paper.title not in seen:
            seen.add(paper.title)
            references.append(
                Reference(
                    id=f"lib:{paper.id}",
                    title=paper.title,
                    year=_paper_year(paper),
                )
            )
        for reference in paper.references[:20]:
            key = (reference.title or reference.raw or "")[:120]
            if key and key not in seen:
                seen.add(key)
                references.append(reference)
    title = idea.strip()
    if len(title) > 80:
        title = title[:77] + "..."
    return OutlineResponse(
        title=title or "Untitled outline",
        sections=sections,
        references=references,
    )


def render_figure(kind: str, spec: str) -> FigureResponse:
    spec = spec.strip()
    if not spec:
        raise ValueError("spec 不能为空")
    if kind == "mermaid":
        first = spec.splitlines()[0].strip().lower()
        known = (
            "flowchart",
            "graph ",
            "sequencediagram",
            "classdiagram",
            "statediagram",
            "erdiagram",
            "gantt",
            "mindmap",
            "timeline",
            "pie",
            "journey",
            "gitgraph",
        )
        if first.startswith(known):
            return FigureResponse(code=spec, format="mermaid")
        safe = spec.replace('"', "'").replace("\n", " ")
        return FigureResponse(
            code=f'flowchart LR\n  A["{safe}"] --> B["Retrieve"]\n  B --> C["Synthesize"]',
            format="mermaid",
        )
    if kind == "graphviz":
        if spec.startswith("digraph"):
            return FigureResponse(code=spec, format="graphviz")
        safe = spec.replace('"', "'")
        return FigureResponse(
            code=f'digraph G {{\n  rankdir=LR;\n  "{safe}" -> "Retrieve" -> "Synthesize";\n}}',
            format="graphviz",
        )
    if kind == "tikz":
        if "\\begin{tikzpicture}" in spec:
            return FigureResponse(code=spec, format="tikz")
        return FigureResponse(
            code=(
                "\\begin{tikzpicture}[node distance=1.6cm]\n"
                f"  \\node (idea) {{{spec}}};\n"
                "  \\node (retrieve) [right=of idea] {Retrieve};\n"
                "  \\draw[->] (idea) -- (retrieve);\n"
                "\\end{tikzpicture}"
            ),
            format="tikz",
        )
    raise ValueError(f"不支持的图形类型: {kind}")


def csv_to_chart(csv_text: str, title: str) -> ChartResponse:
    text = csv_text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    columns = [column for column in (reader.fieldnames or []) if column]
    rows = [
        row
        for row in reader
        if any(str(value).strip() for value in row.values() if value is not None)
    ][:200]
    if not columns or not rows:
        raise ValueError("CSV 需要表头和至少一行数据")

    numeric_columns = [
        column for column in columns if _is_numeric_column(rows, column)
    ][:8]
    if not numeric_columns:
        raise ValueError("CSV 中没有可绘制的数值列")

    x_column = next(
        (column for column in columns if column not in numeric_columns),
        columns[0],
    )
    series_columns = [
        column for column in numeric_columns if column != x_column
    ]
    if not series_columns:
        raise ValueError("CSV 至少需要一列类别 + 一列数值，或两列数值")

    categories = [_cell(row.get(x_column)) for row in rows]
    series = []
    for column in series_columns:
        series.append(
            {
                "name": column,
                "type": "line",
                "smooth": True,
                "symbol": "circle",
                "symbolSize": 6,
                "showSymbol": len(rows) <= 24,
                "connectNulls": False,
                "endLabel": {
                    "show": len(series_columns) <= 4,
                    "formatter": "{a}",
                    "color": "#5A625C",
                    "fontSize": 11,
                },
                "lineStyle": {"width": 2},
                "emphasis": {"focus": "series"},
                "data": [_number(row.get(column)) for row in rows],
            }
        )

    option = {
        "color": CHART_COLORS[: len(series_columns)],
        "backgroundColor": "transparent",
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "cross", "crossStyle": {"color": "#B9BDB6"}},
            "backgroundColor": "#FCFCFB",
            "borderColor": "#D8D4C8",
            "textStyle": {"color": "#1D2420", "fontSize": 12},
        },
        "legend": {
            "bottom": 0,
            "icon": "roundRect",
            "itemWidth": 10,
            "itemHeight": 10,
            "textStyle": {"color": "#5A625C", "fontSize": 12},
        },
        "grid": {"left": 56, "right": 32, "top": 36, "bottom": 64},
        "xAxis": {
            "type": "category",
            "data": categories,
            "boundaryGap": False,
            "axisLine": {"lineStyle": {"color": "#C9CEC5"}},
            "axisTick": {"show": False},
            "axisLabel": {
                "color": "#5A625C",
                "fontSize": 11,
                "hideOverlap": True,
            },
        },
        "yAxis": {
            "type": "value",
            "splitLine": {"lineStyle": {"color": "#E6E8E2", "type": "dashed"}},
            "axisLabel": {"color": "#5A625C", "fontSize": 11},
        },
        "series": series,
        "animationDuration": 400,
    }
    caption = (
        f"图 1. {title}：{'、'.join(series_columns)} 随 {x_column} 的变化。"
    )
    return ChartResponse(
        option=option,
        caption=caption,
        columns=columns,
        rows=[
            {column: _cell(row.get(column)) for column in columns}
            for row in rows[:50]
        ],
    )


def _citation_for_paper(paper: Paper) -> Citation:
    block = paper.blocks[0] if paper.blocks else None
    return Citation(
        paper_id=paper.id,
        paper_title=paper.title,
        page=block.page if block else 1,
        block_id=block.id if block else "metadata",
        quote=(block.text[:240] if block else (paper.title or paper.filename)),
        score=0.0,
        bbox=block.bbox if block else None,
        bbox_space=block.bbox_space if block else "bottom-left",  # type: ignore[arg-type]
    )


def _paper_year(paper: Paper) -> int | None:
    value = paper.metadata.get("year")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_numeric_column(rows: list[dict], column: str) -> bool:
    values = [row.get(column) for row in rows]
    non_empty = [value for value in values if str(value or "").strip()]
    if not non_empty:
        return False
    numeric = [value for value in non_empty if _number(value) is not None]
    return len(numeric) >= 1 and len(numeric) / len(non_empty) >= 0.5


def _number(value) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def _cell(value) -> str:
    return str(value or "").strip()
