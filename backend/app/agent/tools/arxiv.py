"""arXiv search and download-into-library tools."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.core.config import settings
from app.models.schemas import Paper, PaperStatus, ParsedPaper
from app.services.discovery import search_arxiv
from app.services.indexing import index_paper
from app.services.jobs import jobs
from app.services.parsing import parse_pdf
from app.store import paper_store

logger = logging.getLogger(__name__)

_MAX_PDF_BYTES = 40 * 1024 * 1024
_PARSE_WAIT_SECONDS = 120.0

_ARXIV_ID_RE = re.compile(
    r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)", re.I
)

_background_parse_tasks: set[asyncio.Task[None]] = set()


class ArxivSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class ArxivDownloadArgs(BaseModel):
    arxiv_id: str | None = None
    title: str | None = None


class ArxivSearchTool(Tool):
    name = "arxiv.search"
    description = "在 arXiv 上按主题检索论文，返回标题、作者、年份与链接。"
    args_model = ArxivSearchArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        search_args: ArxivSearchArgs = args  # type: ignore[assignment]
        try:
            hits = await search_arxiv(search_args.query, search_args.limit)
        except Exception as exc:
            logger.warning("arxiv.search failed: %s", exc)
            return ToolResult(ok=False, summary=f"arXiv 检索失败：{exc}")
        if not hits:
            return ToolResult(ok=True, summary="arXiv 没有返回结果。", data={"hits": []})
        titles = "、".join(hit.title[:80] for hit in hits[:3])
        return ToolResult(
            ok=True,
            summary=f"找到 {len(hits)} 篇：{titles}",
            data={"hits": [hit.model_dump() for hit in hits]},
        )


class ArxivDownloadTool(Tool):
    name = "arxiv.download"
    description = (
        "按 arXiv ID 或标题下载论文 PDF 并入库解析；"
        "只允许 https://arxiv.org/pdf/<id> 这一种来源。"
    )
    args_model = ArxivDownloadArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        download_args: ArxivDownloadArgs = args  # type: ignore[assignment]
        arxiv_id, hit = await _resolve_target(download_args, context.question)
        if arxiv_id is None:
            return ToolResult(
                ok=False,
                summary=f"没有找到可下载的 arXiv 论文：{download_args.title or ''}",
            )

        existing = _existing_paper(arxiv_id)
        if existing is not None:
            state = "已解析可检索" if existing.status == PaperStatus.ready else "已入库"
            return ToolResult(
                ok=True,
                summary=f"arXiv {arxiv_id} 已在库中（{state}）",
                data={"paper_id": existing.id, "exists": True},
            )

        try:
            content = await _download_pdf(arxiv_id)
        except _DownloadError as exc:
            return ToolResult(ok=False, summary=str(exc))

        settings.ensure_dirs()
        paper_id = uuid.uuid4().hex[:12]
        path = settings.upload_dir / f"{paper_id}.pdf"
        path.write_bytes(content)

        title = hit.title if hit is not None and hit.title else f"{arxiv_id}.pdf"
        paper = Paper(
            id=paper_id,
            filename=f"{arxiv_id}.pdf",
            title=title,
            metadata={
                "file_path": str(path),
                "size_bytes": len(content),
                "arxiv_id": arxiv_id,
                "source": "arxiv",
            },
        )
        paper_store.add(paper)
        job = jobs.create(paper_id)
        task = asyncio.create_task(_parse_background(job.id, paper_id, path))
        _background_parse_tasks.add(task)
        task.add_done_callback(_background_parse_tasks.discard)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_PARSE_WAIT_SECONDS)
            state = "解析完成，可检索"
        except TimeoutError:
            state = "已下载，解析仍在后台进行，稍后可到书架查看"

        return ToolResult(
            ok=True,
            summary=f"arXiv {arxiv_id} 已下载入库：{state}",
            data={"paper_id": paper_id, "arxiv_id": arxiv_id, "title": title},
            artifacts=[
                {"kind": "library", "label": "去书架查看", "paper_id": paper_id}
            ],
        )


class _DownloadError(Exception):
    pass


async def _resolve_target(
    args: ArxivDownloadArgs, question: str
) -> tuple[str | None, Any]:
    if args.arxiv_id:
        cleaned = _clean_id(args.arxiv_id)
        if cleaned is None:
            return None, None
        try:
            hits = await search_arxiv(cleaned, 1)
            hit = hits[0] if hits else None
        except Exception:
            hit = None
        return cleaned, hit
    if args.title:
        try:
            hits = await search_arxiv(args.title, 3)
        except Exception as exc:
            logger.warning("arxiv title search failed: %s", exc)
            return None, None
        for hit in hits:
            if hit.arxiv_id:
                return hit.arxiv_id, hit
        return None, None
    match = _ARXIV_ID_RE.search(question)
    if match:
        cleaned = _clean_id(match.group(1))
        return cleaned, None
    return None, None


def _clean_id(value: str) -> str | None:
    text = value.strip()
    text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text, flags=re.I)
    text = re.sub(r"\.pdf$", "", text, flags=re.I)
    return text if _ARXIV_ID_RE.fullmatch(text) else None


def _existing_paper(arxiv_id: str) -> Paper | None:
    return next(
        (
            paper
            for paper in paper_store.list()
            if str(paper.metadata.get("arxiv_id", "")).strip() == arxiv_id
        ),
        None,
    )


async def _download_pdf(arxiv_id: str) -> bytes:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=60
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise _DownloadError(f"arXiv 下载失败：HTTP {response.status_code}")
            if "text/html" in response.headers.get("content-type", ""):
                base_id = arxiv_id.rsplit("v", 1)[0]
                if base_id != arxiv_id:
                    response = await client.get(f"https://arxiv.org/pdf/{base_id}")
                    if response.status_code != 200:
                        raise _DownloadError(
                            f"arXiv 下载失败：HTTP {response.status_code}"
                        )
                else:
                    raise _DownloadError("arXiv 返回了网页而非 PDF，ID 可能无效")
            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > _MAX_PDF_BYTES:
                raise _DownloadError("PDF 超过 40MB 限制")
            chunks: list[bytes] = []
            received = 0
            async for chunk in response.aiter_bytes(chunk_size=65536):
                received += len(chunk)
                if received > _MAX_PDF_BYTES:
                    raise _DownloadError("PDF 超过 40MB 限制")
                chunks.append(chunk)
            return b"".join(chunks)
    except _DownloadError:
        raise
    except Exception as exc:
        raise _DownloadError(f"arXiv 下载失败：{exc}") from exc


async def _parse_background(job_id: str, paper_id: str, path: Path) -> None:
    paper = paper_store.get(paper_id)
    if paper is None:
        _fail_job(job_id, "论文不存在")
        return

    def progress(stage: str, current: int, total: int, message: str) -> None:
        percent = round(min(current, total) / total * 100, 1) if total else 0.0
        jobs.update(
            job_id,
            status="running",
            stage=stage,
            current=current,
            total=total,
            percent=percent,
            message=message,
        )

    try:
        parsed: ParsedPaper = await asyncio.to_thread(parse_pdf, path, progress)
        updated = paper_store.update(
            paper_id,
            status=PaperStatus.ready,
            pages=parsed.pages,
            blocks=parsed.blocks,
            references=parsed.references,
            parse_engine=parsed.parse_engine,
            metadata={**paper.metadata, **parsed.metadata, "file_path": str(path)},
        )
        if updated is None:
            raise RuntimeError("论文不存在")
        jobs.update(job_id, stage="index", message="建立检索索引")
        await asyncio.to_thread(index_paper, updated)
        jobs.update(
            job_id,
            status="done",
            stage="done",
            current=parsed.pages,
            total=parsed.pages,
            percent=100.0,
            message=f"解析完成：{len(parsed.blocks)} 个文本块",
        )
    except Exception as exc:
        paper_store.update(
            paper_id,
            status=PaperStatus.failed,
            metadata={**paper.metadata, "parse_error": str(exc)},
        )
        _fail_job(job_id, str(exc))


def _fail_job(job_id: str, error: str) -> None:
    jobs.update(
        job_id,
        status="failed",
        stage="failed",
        error=error,
        message=f"解析失败：{error}",
    )
