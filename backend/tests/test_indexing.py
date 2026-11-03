from __future__ import annotations

from app.models.schemas import Block, Paper
from app.services.indexing import InMemoryIndex


def _paper(paper_id: str, *texts: str, title: str | None = None) -> Paper:
    return Paper(
        id=paper_id,
        filename=f"{paper_id}.pdf",
        title=title or f"Paper {paper_id}",
        blocks=[
            Block(id=f"b{index}", page=index + 1, text=text)
            for index, text in enumerate(texts)
        ],
    )


def test_remove_paper_drops_all_its_chunks() -> None:
    paper = Paper(
        id="p1",
        filename="paper.pdf",
        title="A Test Paper",
        blocks=[
            Block(
                id="b1",
                page=1,
                text="attention transformer encoder decoder " * 10,
            )
        ],
    )
    index = InMemoryIndex()
    index.upsert_paper(paper)
    assert index.count() >= 2
    index.remove_paper("p1")
    assert index.count() == 0


def test_bm25_ranks_exact_rare_term_match_first() -> None:
    index = InMemoryIndex()
    index.upsert_paper(
        _paper("p1", "training steps and epochs for the transformer model")
    )
    index.upsert_paper(
        _paper("p2", "warmup steps were 4000 before the learning rate decay")
    )
    hits = index.search_bm25("warmup steps", top_k=2)
    assert hits
    assert hits[0][0].paper_id == "p2"


def test_search_hybrid_dedups_same_block_across_legs() -> None:
    index = InMemoryIndex()
    index.upsert_paper(
        _paper("p1", "warmup steps were 4000 in this training setup")
    )
    hits = index.search_hybrid("warmup steps", top_k=10)
    keys = [(chunk.paper_id, chunk.block_id) for chunk, _ in hits]
    assert len(keys) == len(set(keys))
    assert keys[0] == ("p1", "b0")


def test_hybrid_and_bm25_respect_paper_filter() -> None:
    index = InMemoryIndex()
    index.upsert_paper(
        _paper("p1", "warmup steps were 4000 in this training setup")
    )
    index.upsert_paper(
        _paper("p2", "warmup steps followed a different schedule here")
    )
    hybrid = index.search_hybrid("warmup steps", paper_ids=["p2"], top_k=10)
    assert hybrid
    assert all(chunk.paper_id == "p2" for chunk, _ in hybrid)
    bm25 = index.search_bm25("warmup steps", paper_ids=["p2"], top_k=10)
    assert bm25
    assert all(chunk.paper_id == "p2" for chunk, _ in bm25)


def test_hybrid_prefers_keyword_chunk_without_vector_leg() -> None:
    index = InMemoryIndex()
    index.upsert_paper(
        _paper("p1", "warmup steps were 4000 in this training setup")
    )
    index.upsert_paper(
        _paper("p2", "the optimizer increased the rate gradually early on")
    )
    hits = index.search_hybrid("warmup steps", top_k=10)
    assert hits[0][0].paper_id == "p1"
    assert all(chunk.paper_id != "p2" for chunk, _ in hits)


def test_hybrid_merges_vector_leg_for_synonym_recall(monkeypatch) -> None:
    index = InMemoryIndex()
    index.upsert_paper(
        _paper("p1", "warmup steps were 4000 in this training setup")
    )
    index.upsert_paper(
        _paper("p2", "the optimizer increased the rate gradually early on")
    )
    monkeypatch.setattr(
        index,
        "_search_vector",
        lambda query, paper_ids=None, top_k=6: [(index._chunks["p2:b0"], 0.9)],
    )
    hits = index.search_hybrid("warmup steps", top_k=10)
    papers = [chunk.paper_id for chunk, _ in hits]
    assert "p2" in papers


def test_upsert_replaces_stats_without_double_counting() -> None:
    index = InMemoryIndex()
    index.upsert_paper(
        _paper("p1", "warmup steps were 4000 in this training setup")
    )
    index.upsert_paper(
        _paper("p1", "warmup steps were 8000 in the revised setup")
    )
    assert index._df.get("warmup") == 1
    assert index._doc_count == 2  # metadata chunk + one body chunk


def test_remove_paper_updates_document_frequency() -> None:
    index = InMemoryIndex()
    index.upsert_paper(
        _paper("p1", "warmup steps were 4000 in this training setup")
    )
    index.upsert_paper(
        _paper("p2", "the transformer model processes sequences in parallel")
    )
    assert index._df.get("warmup") == 1
    index.remove_paper("p1")
    assert "warmup" not in index._df
    assert index._df.get("transformer") == 1
