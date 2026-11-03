"""Chunk indexing: Qdrant + BGE-M3 when available, in-memory BM25-ish fallback."""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.models.schemas import Paper
from app.services.text import keywords

logger = logging.getLogger(__name__)

BM25_K1 = 1.5
BM25_B = 0.75
HYBRID_CANDIDATE_POOL = 60
HYBRID_BM25_WEIGHT = 0.6
HYBRID_OVERLAP_WEIGHT = 0.4
VECTOR_DENSE_WEIGHT = 0.5
VECTOR_BM25_WEIGHT = 0.3
VECTOR_OVERLAP_WEIGHT = 0.2
VECTOR_BATCH_SIZE = 32


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


def _minmax_norm(values: list[float]) -> list[float]:
    """Normalize scores to [0, 1]; a flat leg contributes nothing."""

    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


class InMemoryIndex:
    """Deterministic fallback that keeps the whole flow demoable without services."""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._df: dict[str, int] = {}
        self._doc_count = 0
        self._total_len = 0
        self._vec_cache: dict[str, list[float]] = {}
        self._vector_disabled = False

    # -- incremental BM25 statistics --

    def _add_stats(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            tokens = _tokens(chunk.text)
            self._doc_count += 1
            self._total_len += len(tokens)
            for token in set(tokens):
                self._df[token] = self._df.get(token, 0) + 1

    def _drop_stats(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            tokens = _tokens(chunk.text)
            self._doc_count = max(0, self._doc_count - 1)
            self._total_len = max(0, self._total_len - len(tokens))
            for token in set(tokens):
                count = self._df.get(token, 0)
                if count <= 1:
                    self._df.pop(token, None)
                else:
                    self._df[token] = count - 1

    @property
    def _avgdl(self) -> float:
        return self._total_len / self._doc_count if self._doc_count else 0.0

    def upsert_paper(self, paper: Paper) -> int:
        old_chunks = [chunk for chunk in self._chunks.values() if chunk.paper_id == paper.id]
        self._drop_stats(old_chunks)
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.paper_id != paper.id
        }
        self._vec_cache = {
            chunk_id: vector
            for chunk_id, vector in self._vec_cache.items()
            if not chunk_id.startswith(f"{paper.id}:")
        }
        chunks = _chunks_from_paper(paper)
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
        self._add_stats(chunks)
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

    def search_bm25(
        self, query: str, paper_ids: list[str] | None = None, top_k: int = 6
    ) -> list[tuple[Chunk, float]]:
        """Pure-Python BM25 over the same tokenization as the overlap leg."""

        query_tokens = _tokens(query)
        if not query_tokens or self._doc_count == 0:
            return []
        avgdl = self._avgdl or 1.0
        doc_count = self._doc_count
        scored: list[tuple[Chunk, float]] = []
        for chunk in self._chunks.values():
            if paper_ids and chunk.paper_id not in paper_ids:
                continue
            tokens = _tokens(chunk.text)
            if not tokens:
                continue
            term_freq: dict[str, int] = {}
            for token in tokens:
                term_freq[token] = term_freq.get(token, 0) + 1
            score = 0.0
            for token in query_tokens:
                df = self._df.get(token, 0)
                freq = term_freq.get(token, 0)
                if df == 0 or freq == 0:
                    continue
                idf = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
                denominator = freq + BM25_K1 * (
                    1 - BM25_B + BM25_B * len(tokens) / avgdl
                )
                score += idf * (freq * (BM25_K1 + 1)) / denominator
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    # -- optional dense leg (OpenAI-compatible /embeddings) --

    def _vector_ready(self) -> bool:
        return bool(settings.embedding_base_url) and not self._vector_disabled

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        import httpx

        url = settings.embedding_base_url.rstrip("/") + "/embeddings"
        api_key = settings.embedding_api_key or settings.llm_api_key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        with httpx.Client(timeout=20) as client:
            response = client.post(
                url,
                json={"model": settings.embedding_model, "input": texts},
                headers=headers,
            )
        response.raise_for_status()
        rows = sorted(
            response.json().get("data", []), key=lambda item: item.get("index", 0)
        )
        return [[float(value) for value in row["embedding"]] for row in rows]

    def _ensure_vector_cache(self, paper_ids: list[str] | None) -> None:
        missing = [
            (chunk_id, chunk)
            for chunk_id, chunk in self._chunks.items()
            if chunk_id not in self._vec_cache
            and (paper_ids is None or chunk.paper_id in paper_ids)
        ]
        for start in range(0, len(missing), VECTOR_BATCH_SIZE):
            batch = missing[start : start + VECTOR_BATCH_SIZE]
            vectors = self._embed_texts([chunk.text for _, chunk in batch])
            if not vectors or len(vectors) != len(batch):
                raise RuntimeError("embedding batch size mismatch")
            for (chunk_id, _), vector in zip(batch, vectors, strict=True):
                self._vec_cache[chunk_id] = _normalize(vector)

    def _search_vector(
        self, query: str, paper_ids: list[str] | None = None, top_k: int = 6
    ) -> list[tuple[Chunk, float]]:
        if not self._vector_ready():
            return []
        try:
            self._ensure_vector_cache(paper_ids)
            query_vector = self._embed_texts([query])
            if not query_vector:
                return []
            query_vector = _normalize(query_vector[0])
            scored: list[tuple[Chunk, float]] = []
            for chunk_id, vector in self._vec_cache.items():
                chunk = self._chunks.get(chunk_id)
                if chunk is None:
                    continue
                if paper_ids and chunk.paper_id not in paper_ids:
                    continue
                similarity = _dot(query_vector, vector)
                if similarity > 0:
                    scored.append((chunk, similarity))
            scored.sort(key=lambda item: item[1], reverse=True)
            return scored[:top_k]
        except Exception as exc:
            logger.warning("Vector leg failed, disabling it: %s", exc)
            self._vector_disabled = True
            return []

    def search_hybrid(
        self, query: str, paper_ids: list[str] | None = None, top_k: int = 6
    ) -> list[tuple[Chunk, float]]:
        """Merge overlap, BM25 and (optionally) dense cosine legs.

        Each leg is min-max normalized over the pooled candidate set so scores
        become comparable; without EMBEDDING_BASE_URL the dense leg is skipped
        and BM25/overlap share 0.6/0.4.
        """

        overlap_hits = self.search(query, paper_ids=paper_ids, top_k=HYBRID_CANDIDATE_POOL)
        bm25_hits = self.search_bm25(query, paper_ids=paper_ids, top_k=HYBRID_CANDIDATE_POOL)
        vector_hits = self._search_vector(
            query, paper_ids=paper_ids, top_k=HYBRID_CANDIDATE_POOL
        )

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for chunk, score in overlap_hits:
            entry = merged.setdefault(
                (chunk.paper_id, chunk.block_id),
                {"chunk": chunk, "overlap": 0.0, "bm25": 0.0, "vector": 0.0},
            )
            entry["overlap"] = max(entry["overlap"], score)
        for chunk, score in bm25_hits:
            entry = merged.setdefault(
                (chunk.paper_id, chunk.block_id),
                {"chunk": chunk, "overlap": 0.0, "bm25": 0.0, "vector": 0.0},
            )
            entry["bm25"] = max(entry["bm25"], score)
        for chunk, score in vector_hits:
            entry = merged.setdefault(
                (chunk.paper_id, chunk.block_id),
                {"chunk": chunk, "overlap": 0.0, "bm25": 0.0, "vector": 0.0},
            )
            entry["vector"] = max(entry["vector"], score)

        if not merged:
            return []
        entries = list(merged.values())
        overlap_norm = _minmax_norm([entry["overlap"] for entry in entries])
        bm25_norm = _minmax_norm([entry["bm25"] for entry in entries])
        vector_norm = _minmax_norm([entry["vector"] for entry in entries])
        scored: list[tuple[Chunk, float]] = []
        for entry, ov_n, bm_n, vec_n in zip(
            entries, overlap_norm, bm25_norm, vector_norm, strict=True
        ):
            if vector_hits:
                score = (
                    VECTOR_DENSE_WEIGHT * vec_n
                    + VECTOR_BM25_WEIGHT * bm_n
                    + VECTOR_OVERLAP_WEIGHT * ov_n
                )
            else:
                score = HYBRID_BM25_WEIGHT * bm_n + HYBRID_OVERLAP_WEIGHT * ov_n
            scored.append((entry["chunk"], score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._chunks)

    def remove_paper(self, paper_id: str) -> None:
        old_chunks = [chunk for chunk in self._chunks.values() if chunk.paper_id == paper_id]
        self._drop_stats(old_chunks)
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.paper_id != paper_id
        }
        self._vec_cache = {
            chunk_id: vector
            for chunk_id, vector in self._vec_cache.items()
            if not chunk_id.startswith(f"{paper_id}:")
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

    def search_hybrid(
        self, query: str, paper_ids: list[str] | None = None, top_k: int = 6
    ) -> list[tuple[Chunk, float]]:
        """Qdrant's dense search is already the strongest leg; keep the name
        uniform with the in-memory index so callers stay index-agnostic."""

        return self.search(query, paper_ids=paper_ids, top_k=top_k)

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
