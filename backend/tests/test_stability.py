from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.api.v1.papers as papers_module
from app.core.config import settings
from app.main import app
from app.services.jobs import JobStore
from app.store import PaperStore

client = TestClient(app)

_MINIMAL_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _upload(filename: str, content: bytes, content_type: str):
    return client.post(
        "/api/v1/papers",
        files={"file": (filename, content, content_type)},
    )


def test_health_reports_stability_fields() -> None:
    payload = client.get("/api/v1/health").json()
    assert isinstance(payload["index_chunks"], int)
    assert payload["memory_rss_mb"] is None or isinstance(payload["memory_rss_mb"], float)
    assert payload["llm_latency_ms"] is None or isinstance(payload["llm_latency_ms"], float)


def test_request_id_echoes_header() -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"


def test_request_id_generated_when_missing() -> None:
    response = client.get("/api/v1/health")
    assert len(response.headers["X-Request-ID"]) == 12


def test_unhandled_error_returns_request_id() -> None:
    def boom() -> None:
        raise RuntimeError("boom")

    app.add_api_route("/_boom", boom, methods=["GET"], include_in_schema=False)
    try:
        failing_client = TestClient(app, raise_server_exceptions=False)
        response = failing_client.get("/_boom")
    finally:
        added = next(
            route
            for route in app.routes
            if getattr(route, "path", "") == "/_boom"
        )
        app.routes.remove(added)

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "服务器内部错误"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_upload_rejects_wrong_extension() -> None:
    response = _upload("paper.txt", _MINIMAL_PDF, "application/pdf")
    assert response.status_code == 400
    assert response.json()["detail"] == "只接受 PDF 文件"


def test_upload_rejects_wrong_mime() -> None:
    response = _upload("paper.pdf", _MINIMAL_PDF, "text/plain")
    assert response.status_code == 400
    assert response.json()["detail"] == "只接受 PDF 文件"


def test_upload_rejects_missing_pdf_header() -> None:
    response = _upload("paper.pdf", b"definitely not a pdf", "application/pdf")
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_upload_rejects_oversize(monkeypatch) -> None:
    tiny = replace(settings, max_upload_mb=0)
    monkeypatch.setattr(papers_module, "settings", tiny)
    response = _upload("paper.pdf", _MINIMAL_PDF, "application/pdf")
    assert response.status_code == 413


def test_upload_page_limit_removes_file(
    monkeypatch, tmp_path: Path
) -> None:
    tmp_settings = replace(settings, upload_dir=tmp_path)
    monkeypatch.setattr(papers_module, "settings", tmp_settings)

    def too_many_pages(_path: Path) -> None:
        raise HTTPException(status_code=413, detail="PDF 页数过多")

    monkeypatch.setattr(papers_module, "_check_page_limit", too_many_pages)
    response = _upload("paper.pdf", _MINIMAL_PDF, "application/pdf")
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_upload_success_stores_file(
    monkeypatch, tmp_path: Path
) -> None:
    store = PaperStore(tmp_path / "papers.db")
    monkeypatch.setattr(papers_module, "paper_store", store)
    monkeypatch.setattr(
        papers_module,
        "settings",
        replace(settings, upload_dir=tmp_path),
    )
    monkeypatch.setattr(papers_module, "_check_page_limit", lambda _path: None)
    try:
        response = _upload("paper.pdf", _MINIMAL_PDF, "application/pdf")
        assert response.status_code == 201
        paper_id = response.json()["paper"]["id"]
        assert (tmp_path / f"{paper_id}.pdf").exists()
        assert store.get(paper_id) is not None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_parse_concurrency_is_capped(monkeypatch, tmp_path: Path) -> None:
    store = PaperStore(tmp_path / "papers.db")
    store.add(
        papers_module.Paper(
            id="p1",
            filename="p1.pdf",
            metadata={"file_path": str(tmp_path / "p1.pdf")},
        )
    )
    jobs_store = JobStore(tmp_path / "jobs.db")
    monkeypatch.setattr(papers_module, "paper_store", store)
    monkeypatch.setattr(papers_module, "jobs", jobs_store)

    active = 0
    max_active = 0
    starts: list[float] = []

    async def fake_parse(job_id: str, paper_id: str, path: Path, paper: Any) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        starts.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.15)
        active -= 1
        jobs_store.update(job_id, status="done", stage="done", message="ok")

    monkeypatch.setattr(papers_module, "_parse_paper", fake_parse)
    job_ids = [jobs_store.create("p1").id for _ in range(3)]
    try:
        await asyncio.gather(
            *(
                papers_module._run_parse(job_id, "p1", tmp_path / "p1.pdf")
                for job_id in job_ids
            )
        )
    finally:
        store.close()
        jobs_store.close()

    assert max_active == settings.parse_concurrency == 2
    assert len(starts) == 3
    assert starts[2] - starts[0] >= 0.14
