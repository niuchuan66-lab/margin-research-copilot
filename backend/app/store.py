from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import RLock

from app.core.config import settings
from app.models.schemas import Paper, PaperStatus, PaperSummary

logger = logging.getLogger(__name__)


class PaperStore:
    """Paper repository backed by SQLite with an in-process cache.

    The cache keeps API reads fast; every mutation is written through to
    `data/margin.db`. If SQLite cannot be opened the store degrades to the
    previous in-memory behaviour so the API still starts.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._papers: dict[str, Paper] = {}
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
                "CREATE TABLE IF NOT EXISTS papers ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            self._conn.commit()
            self._load()
        except Exception as exc:
            logger.warning("SQLite unavailable, using in-memory papers: %s", exc)
            self._conn = None

    def _load(self) -> None:
        if self._conn is None:
            return
        rows = self._conn.execute("SELECT payload FROM papers").fetchall()
        for (payload,) in rows:
            try:
                paper = Paper.model_validate_json(payload)
            except Exception as exc:
                logger.warning("Skipping corrupt paper row: %s", exc)
                continue
            if paper.status == PaperStatus.parsing:
                paper = paper.model_copy(
                    update={
                        "status": PaperStatus.failed,
                        "metadata": {
                            **paper.metadata,
                            "parse_error": "服务重启，解析任务中断",
                        },
                    }
                )
                self._persist(paper)
            self._papers[paper.id] = paper

    def _persist(self, paper: Paper) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO papers(id, payload) VALUES (?, ?)",
            (paper.id, paper.model_dump_json()),
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

    def add(self, paper: Paper) -> Paper:
        with self._lock:
            self._papers[paper.id] = paper
            self._persist(paper)
        return paper

    def get(self, paper_id: str) -> Paper | None:
        with self._lock:
            return self._papers.get(paper_id)

    def list(self) -> list[Paper]:
        with self._lock:
            return sorted(
                self._papers.values(),
                key=lambda paper: paper.created_at,
                reverse=True,
            )

    def summaries(self) -> list[PaperSummary]:
        return [
            PaperSummary(
                id=paper.id,
                filename=paper.filename,
                title=paper.title,
                status=paper.status,
                pages=paper.pages,
                parse_engine=paper.parse_engine,
                created_at=paper.created_at,
            )
            for paper in self.list()
        ]

    def update(self, paper_id: str, **fields) -> Paper | None:
        with self._lock:
            paper = self._papers.get(paper_id)
            if paper is None:
                return None
            updated = paper.model_copy(update=fields)
            self._papers[paper_id] = updated
            self._persist(updated)
            return updated

    def delete(self, paper_id: str) -> bool:
        with self._lock:
            if paper_id not in self._papers:
                return False
            del self._papers[paper_id]
            if self._conn is not None:
                self._conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
                self._conn.commit()
            return True


paper_store = PaperStore()
