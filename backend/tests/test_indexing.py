from __future__ import annotations

from app.models.schemas import Block, Paper
from app.services.indexing import InMemoryIndex


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
