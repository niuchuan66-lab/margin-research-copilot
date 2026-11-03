"""PostgreSQL models. Enable with `pip install -e '.[db]'` and swap the
in-memory `PaperStore` for a SQLAlchemy repository when moving past the skeleton.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class PaperRow(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    parse_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    blocks: Mapped[list[BlockRow]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    references: Mapped[list[ReferenceRow]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class BlockRow(Base):
    __tablename__ = "paper_blocks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="paragraph")
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    bbox_space: Mapped[str] = mapped_column(String(16), default="bottom-left")
    section_path: Mapped[list] = mapped_column(JSON, default=list)

    paper: Mapped[PaperRow] = relationship(back_populates="blocks")


class ReferenceRow(Base):
    __tablename__ = "paper_references"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    authors: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(512), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(256), nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)

    paper: Mapped[PaperRow] = relationship(back_populates="references")
