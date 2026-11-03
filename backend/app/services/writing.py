"""Outline, diagram and CSV-to-chart helpers for the writing copilot."""

from __future__ import annotations

import csv
import io
import json
import re

from app.core.config import settings
from app.models.schemas import (
    ChartResponse,
    Citation,
    FigureResponse,
    OutlineResponse,
    OutlineSection,
    Paper,
    Reference,
)
from app.services.llm import chat

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


def _paper_context(paper: Paper, limit: int = 600) -> str:
    abstract = paper.metadata.get("abstract")
    if isinstance(abstract, str) and abstract.strip():
        return " ".join(abstract.split())[:limit]
    for block in paper.blocks[:8]:
        if block.kind.value == "paragraph" and len(block.text) >= 80:
            return " ".join(block.text.split())[:limit]
    return " ".join((paper.title or paper.filename).split())[:limit]


def _json_object(raw: str | None) -> dict | None:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def build_outline_llm(
    idea: str, papers: list[Paper], language: str = "zh"
) -> OutlineResponse:
    """LLM outline constrained to the user's own library, with template fallback."""

    base = build_outline(idea, papers, language)
    if not settings.llm_configured or not papers:
        return base
    library = "\n\n".join(
        f"[{index}] {paper.title or paper.filename} "
        f"({_paper_year(paper) or 'n.d.'})\n{_paper_context(paper)}"
        for index, paper in enumerate(papers[:10], start=1)
    )
    language_rule = "中文" if language == "zh" else "English"
    prompt = (
        "你是学术写作助手。只能使用下面编号文献库中的内容，"
        "不得编造文献、数据、实验结果或结论。\n"
        f"研究想法：{idea}\n\n文献库：\n{library}\n\n"
        f"请用{language_rule}输出严格 JSON，不要输出解释："
        '{"title":"论文标题","sections":[{"heading":"章节名",'
        '"intent":"一句话写作意图","cite":[1,2]}]}。'
        "要求 6-8 个章节，覆盖摘要、引言、相关工作、方法、实验/评估、讨论、结论；"
        "cite 只能填写文献库编号，没有依据就留空。"
    )
    raw = await chat(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1600,
    )
    data = _json_object(raw)
    if not data:
        return base
    sections: list[OutlineSection] = []
    for item in data.get("sections") or []:
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading") or "").strip()
        intent = str(item.get("intent") or "").strip()
        if not heading or not intent:
            continue
        citations: list[Citation] = []
        for value in item.get("cite") or []:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= index <= len(papers):
                citations.append(_citation_for_paper(papers[index - 1]))
        sections.append(
            OutlineSection(
                heading=heading[:120],
                intent=intent[:400],
                citations=citations,
            )
        )
    if len(sections) < 4:
        return base
    title = str(data.get("title") or base.title).strip()[:160] or base.title
    return OutlineResponse(
        title=title, sections=sections, references=base.references
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


def csv_to_chart(
    csv_text: str, title: str, chart_type: str = "line"
) -> ChartResponse:
    if chart_type not in {"line", "bar", "radar"}:
        raise ValueError(f"不支持的图表类型: {chart_type}")
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
        values = [_number(row.get(column)) for row in rows]
        if chart_type == "line":
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
                    "data": values,
                }
            )
        else:
            series.append(
                {
                    "name": column,
                    "type": "bar",
                    "barMaxWidth": 28,
                    "emphasis": {"focus": "series"},
                    "data": values,
                }
            )

    if chart_type == "radar":
        maxima = {
            column: max(
                [value or 0 for value in [_number(row.get(column)) for row in rows]]
                or [0]
            )
            or 1
            for column in series_columns
        }
        option = {
            "color": CHART_COLORS[: len(rows)],
            "backgroundColor": "transparent",
            "tooltip": {},
            "legend": {
                "bottom": 0,
                "icon": "roundRect",
                "itemWidth": 10,
                "itemHeight": 10,
                "textStyle": {"color": "#5A625C", "fontSize": 12},
            },
            "radar": {
                "center": ["50%", "46%"],
                "radius": "62%",
                "indicator": [
                    {"name": column, "max": maxima[column]}
                    for column in series_columns
                ],
                "axisName": {"color": "#5A625C", "fontSize": 11},
                "splitLine": {"lineStyle": {"color": "#E6E8E2"}},
                "splitArea": {"areaStyle": {"color": ["#FCFCFB", "#F7F6F1"]}},
                "axisLine": {"lineStyle": {"color": "#C9CEC5"}},
            },
            "series": [
                {
                    "type": "radar",
                    "symbolSize": 5,
                    "data": [
                        {
                            "name": category,
                            "value": [
                                _number(row.get(column)) or 0
                                for column in series_columns
                            ],
                        }
                        for category, row in zip(categories, rows, strict=False)
                    ],
                }
            ],
            "animationDuration": 400,
        }
        caption = (
            f"图 1. {title}：{len(rows)} 组样本在 "
            f"{'、'.join(series_columns)} 上的雷达对比。"
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
            "boundaryGap": chart_type == "bar",
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
        f"图 1. {title}：{'柱状图' if chart_type == 'bar' else '折线图'}，"
        f"{'、'.join(series_columns)} 随 {x_column} 的变化。"
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


async def csv_to_chart_llm(
    csv_text: str, title: str, chart_type: str = "line"
) -> ChartResponse:
    base = csv_to_chart(csv_text, title, chart_type)
    if not settings.llm_configured:
        return base
    prompt = (
        "你是学术图表助手。根据下面的数据写一句中文学术图注，"
        "只描述数据中可见的趋势或差异，不得编造数值或原因。\n"
        f"图表标题：{title}\n图表类型：{chart_type}\n"
        f"数据（前 10 行）：{json.dumps(base.rows[:10], ensure_ascii=False)}\n"
        "要求：40–120 字，点出主要趋势或最大差异，不要重复“图 1”，"
        "不要使用 Markdown，不要出现编造的统计显著性。"
    )
    raw = await chat(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    if raw:
        line = " ".join(raw.split()).strip().strip('"')
        line = re.sub(r"^图\s*\d+[.、:：]\s*", "", line)
        if len(line) >= 10:
            base.caption = f"图 1. {title}：{line[:180]}"
    return base


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
