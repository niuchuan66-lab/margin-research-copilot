"""Chunk indexing: Qdrant + BGE-M3 when available, in-memory BM25-ish fallback."""

from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.models.schemas import Paper
from app.services.text import keywords

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Chunk:
    id: str
    paper_id: str
    paper_title: str | None
    page: int
    block_id: str
    text: str
    bbox: list[float] | None
    bbox_space: str = "bottom-left"
    section_path: tuple[str, ...] = ()


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = keywords(text)
    cjk = re.findall(r"[一-鿿]", lowered)
    bigrams = ["".join(pair) for pair in zip(cjk, cjk[1:], strict=False)]
    return words + bigrams


def _chunks_from_paper(paper: Paper) -> list[Chunk]:
    chunks: list[Chunk] = []
    if paper.title:
        chunks.append(
            Chunk(
                id=f"{paper.id}:metadata",
                paper_id=paper.id,
                paper_title=paper.title,
                page=1,
                block_id="metadata",
                text=f"Title: {paper.title}",
                bbox=None,
                section_path=("metadata",),
            )
        )
    for block in paper.blocks:
        text = block.text.strip()
        if len(text) < 20:
            continue
        chunks.append(
            Chunk(
                id=f"{paper.id}:{block.id}",
                paper_id=paper.id,
                paper_title=paper.title,
                page=block.page,
                block_id=block.id,
                text=text,
                bbox=block.bbox,
                bbox_space=block.bbox_space,
                section_path=tuple(block.section_path),
            )
        )
    return chunks


class InMemoryIndex:
    """Deterministic fallback that keeps the whole flow demoable without services."""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}

    def upsert_paper(self, paper: Paper) -> int:
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.paper_id != paper.id
        }
        chunks = _chunks_from_paper(paper)
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
        return len(chunks)

    def search(
        self, query: str, paper_ids: list[str] | None = None, top_k: int = 6
    ) -> list[tuple[Chunk, float]]:
        query_tokens = set(_tokens(query))
        if not query_tokens:
            return []
        scored: list[tuple[Chunk, float]] = []
        for chunk in self._chunks.values():
            if paper_ids and chunk.paper_id not in paper_ids:
                continue
            chunk_tokens = _tokens(chunk.text)
            if not chunk_tokens:
                continue
            overlap = sum(1 for token in chunk_tokens if token in query_tokens)
            if overlap == 0:
                continue
            score = overlap / math.sqrt(len(chunk_tokens) + 1)
            if query.lower() in chunk.text.lower():
                score += 0.5
            scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._chunks)

    def remove_paper(self, paper_id: str) -> None:
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.paper_id != paper_id
        }


class QdrantIndex:
    """Qdrant collection with BGE-M3 dense vectors.

    The class is constructed only when Qdrant answers its health probe; any
    failure makes `get_index()` fall back to the in-memory index.
    """

    def __init__(self) -> None:
        from qdrant_client import QdrantClient

        self.client = QdrantClient(url=settings.qdrant_url, timeout=5)
        self.client.get_collections()
        self._embedder: Any | None = None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            from FlagEmbedding import BGEM3FlagModel

            self._embedder = BGEM3FlagModel(settings.embedding_model, use_fp16=True)
        output = self._embedder.encode(
            texts,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return [list(map(float, vector)) for vector in output["dense_vecs"]]

    def _ensure_collection(self, size: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        try:
            self.client.get_collection(settings.qdrant_collection)
        except Exception:
            self.client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )

    def upsert_paper(self, paper: Paper) -> int:
        from qdrant_client.models import PointStruct

        chunks = _chunks_from_paper(paper)
        if not chunks:
            return 0
        vectors = self._embed([chunk.text for chunk in chunks])
        self._ensure_collection(len(vectors[0]))
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.id)),
                vector=vector,
                payload={
                    "chunk_id": chunk.id,
                    "paper_id": chunk.paper_id,
                    "paper_title": chunk.paper_title,
                    "page": chunk.page,
                    "block_id": chunk.block_id,
                    "text": chunk.text,
                    "bbox": chunk.bbox,
                    "bbox_space": chunk.bbox_space,
                    "section_path": list(chunk.section_path),
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self.client.upsert(collection_name=settings.qdrant_collection, points=points)
        return len(points)

    def search(
        self, query: str, paper_ids: list[str] | None = None, top_k: int = 6
    ) -> list[tuple[Chunk, float]]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        vector = self._embed([query])[0]
        query_filter = None
        if paper_ids:
            query_filter = Filter(
                must=[FieldCondition(key="paper_id", match=MatchAny(any=paper_ids))]
            )
        try:
            result = self.client.query_points(
                collection_name=settings.qdrant_collection,
                query=vector,
                limit=top_k,
                query_filter=query_filter,
            )
            points = result.points
        except AttributeError:  # older qdrant-client
            points = self.client.search(
                collection_name=settings.qdrant_collection,
                query_vector=vector,
                limit=top_k,
                query_filter=query_filter,
            )

        hits: list[tuple[Chunk, float]] = []
        for point in points:
            payload = point.payload or {}
            hits.append(
                (
                    Chunk(
                        id=str(payload.get("chunk_id", point.id)),
                        paper_id=str(payload.get("paper_id", "")),
                        paper_title=payload.get("paper_title"),
                        page=int(payload.get("page", 1)),
                        block_id=str(payload.get("block_id", "")),
                        text=str(payload.get("text", "")),
                        bbox=payload.get("bbox"),
                        bbox_space=str(payload.get("bbox_space", "bottom-left")),
                        section_path=tuple(payload.get("section_path") or ()),
                    ),
                    float(point.score),
                )
            )
        return hits

    def count(self) -> int:
        try:
            return int(self.client.count(settings.qdrant_collection).count)
        except Exception:
            return 0

    def remove_paper(self, paper_id: str) -> None:
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            self.client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="paper_id",
                            match=MatchValue(value=paper_id),
                        )
                    ]
                ),
            )
        except Exception as exc:
            logger.warning("Qdrant remove_paper failed: %s", exc)


_index: InMemoryIndex | QdrantIndex | None = None


def get_index() -> InMemoryIndex | QdrantIndex:
    global _index
    if _index is None:
        if settings.qdrant_url:
            try:
                _index = QdrantIndex()
                logger.info("Using Qdrant index at %s", settings.qdrant_url)
            except Exception as exc:
                logger.info("Qdrant unavailable (%s); using in-memory index", exc)
                _index = InMemoryIndex()
        else:
            _index = InMemoryIndex()
    return _index


def index_paper(paper: Paper) -> int:
    return get_index().upsert_paper(paper)


def remove_paper_from_index(paper_id: str) -> None:
    index = get_index()
    remove = getattr(index, "remove_paper", None)
    if callable(remove):
        remove(paper_id)
