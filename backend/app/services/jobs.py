"""Parse-job registry persisted in SQLite so progress survives restarts."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from app.core.config import settings

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "failed"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ParseJob:
    id: str
    paper_id: str
    status: JobStatus = "queued"
    stage: str = "queued"
    current: int = 0
    total: int = 0
    percent: float = 0.0
    message: str = "等待解析"
    error: str | None = None
    dedup: dict[str, Any] | None = None
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None


class JobStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._jobs: dict[str, ParseJob] = {}
        self._lock = RLock()
        self._conn: sqlite3.Connection | None = None
        self._db_path = db_path or (settings.data_dir / "margin.db")
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                self._db_path, check_same_thread=False, timeout=5
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS parse_jobs ("
                "id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            self._conn.commit()
            self._load()
        except Exception as exc:
            logger.warning("SQLite unavailable, using in-memory jobs: %s", exc)
            self._conn = None

    def _load(self) -> None:
        if self._conn is None:
            return
        rows = self._conn.execute("SELECT payload FROM parse_jobs").fetchall()
        for (payload,) in rows:
            try:
                job = ParseJob(**json.loads(payload))
            except Exception as exc:
                logger.warning("Skipping corrupt job row: %s", exc)
                continue
            if job.status in {"queued", "running"}:
                job.status = "failed"
                job.stage = "failed"
                job.error = "服务重启，解析任务中断"
                job.message = "服务重启，解析任务中断"
                job.finished_at = _now()
                self._persist(job)
            self._jobs[job.id] = job

    def _persist(self, job: ParseJob) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO parse_jobs(id, paper_id, payload) VALUES (?, ?, ?)",
            (job.id, job.paper_id, json.dumps(asdict(job), ensure_ascii=False)),
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
                self._conn.close()
                self._conn = None

    def create(self, paper_id: str) -> ParseJob:
        job = ParseJob(id=uuid.uuid4().hex[:12], paper_id=paper_id)
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
        return job

    def get(self, job_id: str) -> ParseJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest_for_paper(self, paper_id: str) -> ParseJob | None:
        with self._lock:
            for job in reversed(list(self._jobs.values())):
                if job.paper_id == paper_id:
                    return job
        return None

    def update(self, job_id: str, **fields: Any) -> ParseJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                setattr(job, key, value)
            if job.total and "current" in fields and "percent" not in fields:
                job.percent = round(min(job.current, job.total) / job.total * 100, 1)
            if job.status in {"done", "failed"} and job.finished_at is None:
                job.finished_at = _now()
            self._persist(job)
            return job


jobs = JobStore()
