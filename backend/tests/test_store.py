from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.models.schemas import Paper, PaperStatus
from app.services.jobs import JobStore
from app.store import PaperStore


def test_paper_store_persists_across_reload() -> None:
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "margin.db"
        store = PaperStore(db_path=db)
        store.add(Paper(id="p1", filename="x.pdf", title="X"))
        store.update("p1", status=PaperStatus.ready)
        store.close()

        reloaded = PaperStore(db_path=db)
        paper = reloaded.get("p1")
        assert paper is not None
        assert paper.status == PaperStatus.ready
        reloaded.close()


def test_delete_persists_across_reload() -> None:
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "margin.db"
        store = PaperStore(db_path=db)
        store.add(Paper(id="p3", filename="z.pdf", title="Z"))
        assert store.delete("p3")
        store.close()

        reloaded = PaperStore(db_path=db)
        assert reloaded.get("p3") is None
        reloaded.close()


def test_interrupted_parse_is_marked_failed_on_reload() -> None:
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "margin.db"
        store = PaperStore(db_path=db)
        store.add(
            Paper(
                id="p2",
                filename="y.pdf",
                title="Y",
                status=PaperStatus.parsing,
            )
        )
        store.close()

        reloaded = PaperStore(db_path=db)
        paper = reloaded.get("p2")
        assert paper is not None
        assert paper.status == PaperStatus.failed
        assert "服务重启" in str(paper.metadata.get("parse_error", ""))
        reloaded.close()


def test_job_store_persists_and_marks_interrupted() -> None:
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "margin.db"
        jobs = JobStore(db_path=db)
        job = jobs.create("p1")
        jobs.update(
            job.id,
            status="running",
            stage="extract",
            current=2,
            total=10,
            percent=20.0,
        )
        jobs.close()

        reloaded = JobStore(db_path=db)
        latest = reloaded.latest_for_paper("p1")
        assert latest is not None
        assert latest.status == "failed"
        assert "服务重启" in str(latest.error)
        reloaded.close()
