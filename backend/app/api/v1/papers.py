from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings
from app.models.schemas import (
    Block,
    DedupActionRequest,
    DedupActionResponse,
    DedupCandidate,
    DedupResult,
    Paper,
    PaperStatus,
    PaperSummary,
    ParseJobResponse,
    UploadResponse,
    VersionDiffResponse,
)
from app.services.dedup import compare, jaccard, shingles, version_number
from app.services.indexing import index_paper, remove_paper_from_index
from app.services.jobs import ParseJob, jobs
from app.services.parsing import parse_pdf
from app.services.version_diff import diff_papers
from app.store import paper_store

router = APIRouter(prefix="/papers", tags=["papers"])

_parse_tasks: set[asyncio.Task[None]] = set()


def _summary(paper: Paper) -> PaperSummary:
    return PaperSummary.model_validate(paper.model_dump())


def _job_response(job: ParseJob) -> ParseJobResponse:
    return ParseJobResponse(
        job_id=job.id,
        paper_id=job.paper_id,
        status=job.status,
        stage=job.stage,
        current=job.current,
        total=job.total,
        percent=job.percent,
        message=job.message,
        error=job.error,
        dedup=job.dedup,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("", response_model=list[PaperSummary])
def list_papers() -> list[PaperSummary]:
    return paper_store.summaries()


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_paper(file: UploadFile = File(...)) -> UploadResponse:  # noqa: B008
    filename = file.filename or "untitled.pdf"
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="只接受 PDF 文件")

    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {settings.max_upload_mb} MB",
        )

    settings.ensure_dirs()
    paper_id = uuid.uuid4().hex[:12]
    path = settings.upload_dir / f"{paper_id}.pdf"
    path.write_bytes(content)

    paper = Paper(
        id=paper_id,
        filename=filename,
        title=Path(filename).stem,
        metadata={"file_path": str(path), "size_bytes": len(content)},
    )
    paper_store.add(paper)
    return UploadResponse(paper=_summary(paper))


@router.get("/{paper_id}", response_model=Paper)
def get_paper(paper_id: str, include_blocks: bool = True) -> Paper:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    if not include_blocks:
        return paper.model_copy(update={"blocks": []})
    return paper


@router.get("/{paper_id}/blocks", response_model=list[Block])
def get_page_blocks(
    paper_id: str,
    page: int = Query(default=1, ge=1),
) -> list[Block]:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return [block for block in paper.blocks if block.page == page]


@router.get("/{paper_id}/file")
def get_paper_file(paper_id: str) -> FileResponse:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    path = Path(str(paper.metadata.get("file_path", "")))
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件已丢失")
    return FileResponse(path, media_type="application/pdf", filename=paper.filename)


@router.post("/{paper_id}/parse", response_model=ParseJobResponse, status_code=202)
async def start_parse(paper_id: str) -> ParseJobResponse:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    path = Path(str(paper.metadata.get("file_path", "")))
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件已丢失")

    current = jobs.latest_for_paper(paper_id)
    if current is not None and current.status in {"queued", "running"}:
        return _job_response(current)

    job = jobs.create(paper_id)
    paper_store.update(paper_id, status=PaperStatus.parsing)
    task = asyncio.create_task(_run_parse(job.id, paper_id, path))
    _parse_tasks.add(task)
    task.add_done_callback(_parse_tasks.discard)
    return _job_response(job)


@router.get("/{paper_id}/parse-status", response_model=ParseJobResponse)
def parse_status(paper_id: str) -> ParseJobResponse:
    job = jobs.latest_for_paper(paper_id)
    if job is None:
        raise HTTPException(status_code=404, detail="还没有解析任务")
    return _job_response(job)


async def _run_parse(job_id: str, paper_id: str, path: Path) -> None:
    paper = paper_store.get(paper_id)
    if paper is None:
        jobs.update(
            job_id,
            status="failed",
            stage="failed",
            error="论文不存在",
            message="论文不存在",
        )
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
        parsed = await asyncio.to_thread(parse_pdf, path, progress)
        meta_title = " ".join(
            str(parsed.metadata.get("title") or "").split()
        )
        derived_title = (
            meta_title
            if meta_title and _looks_like_title(meta_title)
            else _derive_title(parsed.blocks)
        ) or paper.title
        updated = paper_store.update(
            paper_id,
            status=PaperStatus.ready,
            title=derived_title,
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
        dedup = _dedup(updated)
        jobs.update(
            job_id,
            status="done",
            stage="done",
            current=parsed.pages,
            total=parsed.pages,
            percent=100.0,
            message=f"解析完成：{len(parsed.blocks)} 个文本块",
            dedup=dedup.model_dump() if dedup else None,
        )
    except Exception as exc:
        paper_store.update(
            paper_id,
            status=PaperStatus.failed,
            metadata={**paper.metadata, "parse_error": str(exc)},
        )
        jobs.update(
            job_id,
            status="failed",
            stage="failed",
            error=str(exc),
            message=f"解析失败：{exc}",
        )


@router.delete("/{paper_id}")
def delete_paper(paper_id: str) -> dict[str, bool]:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return {"deleted": _delete_paper(paper_id)}


@router.get("/{paper_id}/versions", response_model=list[DedupCandidate])
def paper_versions(paper_id: str) -> list[DedupCandidate]:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    if paper.status != PaperStatus.ready:
        return []
    text = "\n".join(block.text for block in paper.blocks[:200])
    new_shingles = shingles(text)
    results: list[DedupCandidate] = []
    for existing in paper_store.list():
        if existing.id == paper.id or existing.status != PaperStatus.ready:
            continue
        if not existing.blocks:
            continue
        old_text = "\n".join(block.text for block in existing.blocks[:200])
        similarity = jaccard(new_shingles, shingles(old_text))
        if similarity < 0.45:
            continue
        current_version = version_number(paper.filename)
        candidate_version = version_number(existing.filename)
        results.append(
            DedupCandidate(
                paper_id=existing.id,
                title=existing.title,
                similarity=round(similarity, 4),
                reason="同源版本",
                newer_version=(
                    current_version is not None
                    and candidate_version is not None
                    and candidate_version > current_version
                ),
            )
        )
    results.sort(key=lambda item: item.similarity, reverse=True)
    return results


@router.get("/{paper_id}/diff/{old_id}", response_model=VersionDiffResponse)
async def paper_diff(paper_id: str, old_id: str) -> VersionDiffResponse:
    new_paper = paper_store.get(paper_id)
    old_paper = paper_store.get(old_id)
    if new_paper is None or old_paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    if paper_id == old_id:
        raise HTTPException(status_code=400, detail="不能与自身对比")
    return await diff_papers(new_paper, old_paper)


@router.post("/{paper_id}/dedup", response_model=DedupActionResponse)
def resolve_dedup(
    paper_id: str, payload: DedupActionRequest
) -> DedupActionResponse:
    paper = paper_store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    result = _dedup(paper)
    if result is None or not result.candidates:
        raise HTTPException(status_code=400, detail="没有可处理的重复候选")

    candidate = result.candidates[0]
    if payload.candidate_id:
        candidate = next(
            (
                item
                for item in result.candidates
                if item.paper_id == payload.candidate_id
            ),
            None,
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="重复候选不存在")
    if candidate.paper_id == paper_id:
        raise HTTPException(status_code=400, detail="不能与自身去重")

    if payload.action == "replace":
        if not _delete_paper(candidate.paper_id):
            raise HTTPException(status_code=404, detail="旧版论文不存在")
        return DedupActionResponse(
            action="replace",
            kept=paper_id,
            removed=candidate.paper_id,
        )
    return DedupActionResponse(action="keep", kept=paper_id)


def _delete_paper(paper_id: str) -> bool:
    paper = paper_store.get(paper_id)
    if paper is None:
        return False
    path = Path(str(paper.metadata.get("file_path", "")))
    if path.exists():
        path.unlink()
    remove_paper_from_index(paper_id)
    return paper_store.delete(paper_id)


def _derive_title(blocks: list[Block]) -> str | None:
    lines = [
        " ".join(line.split())
        for block in blocks[:6]
        for line in block.text.splitlines()
        if line.strip()
    ]
    for index, candidate in enumerate(lines):
        if not _looks_like_title(candidate):
            continue
        if index + 1 < len(lines):
            following = lines[index + 1]
            if candidate.endswith(":") and _looks_like_title_fragment(following):
                return f"{candidate} {following}"[:220]
            if (
                candidate.isupper()
                and following.isupper()
                and _looks_like_title_fragment(following)
            ):
                return f"{candidate} {following}"[:220]
            if (
                following[:1].islower()
                and len(following.split()) <= 6
                and not candidate.endswith((".", "?", "!"))
            ):
                return f"{candidate} {following}"[:220]
        return candidate
    return None


def _looks_like_title_fragment(line: str) -> bool:
    return 3 <= len(line) <= 120 and not line.endswith((".", ",", ";"))


def _looks_like_title(line: str) -> bool:
    line = line.strip()
    if not 8 <= len(line) <= 220:
        return False
    lowered = line.lower()
    if lowered.startswith(
        (
            "provided",
            "copyright",
            "license",
            "permission",
            "arxiv",
            "this work",
            "abstract",
            "journal of",
            "published in",
            "published as",
            "proceedings",
            "association for computational linguistics",
            "submitted",
            "reviewed on openreview",
            "c 20",
        )
    ):
        return False
    if "@" in line or "http" in lowered:
        return False
    if line.count(",") >= 2 or "∗" in line or "†" in line:
        return False
    words = line.split()
    if not 2 <= len(words) <= 25:
        return False
    if line.endswith((".", "。", ",", "*", "†", "‡")):
        return False
    if not any(char.isalpha() for char in line):
        return False
    return any(char.isupper() for char in line)


def _dedup(paper: Paper) -> DedupResult | None:
    new_text = "\n".join(block.text for block in paper.blocks[:200])
    if not new_text.strip():
        return None
    candidates = [
        (
            existing.id,
            f"{existing.title or ''} {existing.filename}".strip(),
            "\n".join(block.text for block in existing.blocks[:200]),
        )
        for existing in paper_store.list()
        if existing.id != paper.id
        and existing.status == PaperStatus.ready
        and existing.blocks
    ]
    if not candidates:
        return None
    return compare(new_text, paper.filename, candidates)
