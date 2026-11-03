"""Shared Pydantic contracts between the API, services and the frontend."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PaperStatus(StrEnum):
    uploaded = "uploaded"
    parsing = "parsing"
    ready = "ready"
    failed = "failed"


class BlockKind(StrEnum):
    heading = "heading"
    paragraph = "paragraph"
    table = "table"
    formula = "formula"
    figure_caption = "figure_caption"
    reference = "reference"
    other = "other"


class Block(BaseModel):
    id: str
    page: int
    text: str
    bbox: list[float] | None = Field(
        default=None,
        description="[x0, y0, x1, y1] in PDF points; origin is recorded in bbox_space.",
    )
    bbox_space: Literal["bottom-left", "top-left"] = "bottom-left"
    kind: BlockKind = BlockKind.paragraph
    section_path: list[str] = Field(default_factory=list)


class Reference(BaseModel):
    id: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    raw: str | None = None


class ParsedPaper(BaseModel):
    pages: int = 0
    blocks: list[Block] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    parse_engine: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Paper(BaseModel):
    id: str
    filename: str
    title: str | None = None
    status: PaperStatus = PaperStatus.uploaded
    pages: int = 0
    parse_engine: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    blocks: list[Block] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaperSummary(BaseModel):
    id: str
    filename: str
    title: str | None = None
    status: PaperStatus
    pages: int = 0
    parse_engine: str | None = None
    created_at: datetime


class UploadResponse(BaseModel):
    paper: PaperSummary
    dedup: DedupResult | None = None


class DedupCandidate(BaseModel):
    paper_id: str
    title: str | None = None
    similarity: float
    reason: str
    newer_version: bool = False


class DedupResult(BaseModel):
    is_duplicate: bool = False
    similarity: float = 0.0
    action: Literal["accept", "warn", "replace", "keep"] = "accept"
    candidates: list[DedupCandidate] = Field(default_factory=list)


class ParseJobResponse(BaseModel):
    job_id: str
    paper_id: str
    status: Literal["queued", "running", "done", "failed"]
    stage: str
    current: int = 0
    total: int = 0
    percent: float = 0.0
    message: str = ""
    error: str | None = None
    dedup: DedupResult | None = None
    started_at: str
    finished_at: str | None = None


class DedupActionRequest(BaseModel):
    action: Literal["replace", "keep"]
    candidate_id: str | None = None


class DedupActionResponse(BaseModel):
    action: Literal["replace", "keep"]
    kept: str
    removed: str | None = None


class VersionChange(BaseModel):
    kind: Literal["added", "removed", "modified"]
    new_page: int | None = None
    new_bbox: list[float] | None = None
    old_page: int | None = None
    old_bbox: list[float] | None = None
    new_text: str | None = None
    old_text: str | None = None
    similarity: float = 0.0


class VersionDiffResponse(BaseModel):
    new_id: str
    old_id: str
    similarity: float
    changes: list[VersionChange] = Field(default_factory=list)
    summary: str = ""


class Citation(BaseModel):
    paper_id: str
    paper_title: str | None = None
    page: int
    block_id: str
    quote: str
    score: float = 0.0
    bbox: list[float] | None = None
    bbox_space: Literal["bottom-left", "top-left"] = "bottom-left"


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    paper_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=6, ge=1, le=20)


class AnswerResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    model: str = "extractive-fallback"
    grounded: bool = False


class AgentRunRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    paper_ids: list[str] = Field(default_factory=list)


class TranslationRequest(BaseModel):
    paper_id: str
    block_ids: list[str] = Field(default_factory=list)
    target_lang: str = "zh-CN"


class TextTranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    target_lang: str = "zh-CN"


class TextTranslationResponse(BaseModel):
    translation: str | None = None
    status: str = "ok"


class TranslatedBlock(BaseModel):
    block_id: str
    page: int
    bbox: list[float] | None = None
    source: str
    translation: str | None = None
    status: Literal["ok", "not_configured", "error"] = "not_configured"


class DiscoveryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    source: Literal["arxiv", "openalex"] = "arxiv"
    limit: int = Field(default=10, ge=1, le=30)


class DiscoveryHit(BaseModel):
    source: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    github_url: str | None = None
    reason: str | None = None


class RecommendRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=30)


class GraphBuildRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


class SurveyResponse(BaseModel):
    graph_id: str
    markdown: str


class FutureWorkItem(BaseModel):
    idea: str
    paper_id: str
    paper_title: str | None = None
    year: int | None = None
    page: int
    evidence: str


class FutureWorkResponse(BaseModel):
    graph_id: str
    items: list[FutureWorkItem] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    title: str
    year: int | None = None
    citations: int = 0
    centrality: float = 0.0
    is_cornerstone: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float = 1.0


class GraphResponse(BaseModel):
    graph_id: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    algorithm: str = "in-degree"
    summary: str = ""


class OutlineSection(BaseModel):
    heading: str
    intent: str
    citations: list[Citation] = Field(default_factory=list)


class OutlineRequest(BaseModel):
    idea: str = Field(min_length=4, max_length=4000)
    paper_ids: list[str] = Field(default_factory=list)
    language: Literal["zh", "en"] = "zh"


class OutlineResponse(BaseModel):
    title: str
    sections: list[OutlineSection] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)


class FigureRequest(BaseModel):
    kind: Literal["mermaid", "graphviz", "tikz"] = "mermaid"
    spec: str = Field(min_length=1, max_length=4000)


class FigureResponse(BaseModel):
    code: str
    format: str


class ChartRequest(BaseModel):
    csv: str = Field(min_length=3)
    title: str = "Figure"
    chart_type: Literal["line", "bar", "radar"] = "line"


class ChartResponse(BaseModel):
    option: dict[str, Any]
    caption: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    capabilities: dict[str, bool]
    degraded: list[str] = Field(default_factory=list)
    index_chunks: int | None = None
    llm_latency_ms: float | None = None
    memory_rss_mb: float | None = None


UploadResponse.model_rebuild()
