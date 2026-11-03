from __future__ import annotations

import pytest

from app.models.schemas import Block, Paper
from app.services.version_diff import (
    _fallback_summary,
    _summary_pages_valid,
    align_paragraphs,
    build_diff,
    whole_similarity,
)


def _paper(paper_id: str, filename: str, blocks: list[Block]) -> Paper:
    return Paper(id=paper_id, filename=filename, title=f"Paper {paper_id}", blocks=blocks)


def _block(block_id: str, page: int, text: str) -> Block:
    return Block(id=block_id, page=page, text=text, bbox=[10.0, 20.0, 200.0, 40.0])


IDENTICAL = (
    "the transformer uses attention mechanisms to capture long range dependencies "
    "in sequence transduction tasks without any recurrent or convolutional layers"
)

MODIFIED_NEW = (
    "we trained the base model for 100000 steps on eight nvidia p100 gpus for twelve "
    "hours and the big model for three and a half days"
)
MODIFIED_OLD = (
    "we trained the base model for 100000 steps on eight nvidia p100 gpus for twelve "
    "hours while the big model took three and a half days to finish training"
)


def test_identical_paragraphs_produce_no_changes() -> None:
    new = _paper("n", "paper.pdf", [_block("b1", 1, IDENTICAL)])
    old = _paper("o", "paper.pdf", [_block("b1", 1, IDENTICAL)])
    assert align_paragraphs(new, old) == []


def test_added_and_removed_paragraphs_are_classified() -> None:
    new = _paper(
        "n",
        "paper.pdf",
        [
            _block("b1", 1, IDENTICAL),
            _block(
                "b2",
                2,
                "we added a brand new experimental section describing the "
                "evaluation protocol",
            ),
        ],
    )
    old = _paper(
        "o",
        "paper.pdf",
        [
            _block("b1", 1, IDENTICAL),
            _block(
                "b3",
                2,
                "the legacy appendix paragraph documents the original baseline "
                "system",
            ),
        ],
    )
    changes = align_paragraphs(new, old)
    added = [change for change in changes if change.kind == "added"]
    removed = [change for change in changes if change.kind == "removed"]
    assert len(added) == 1
    assert added[0].new_page == 2
    assert added[0].new_bbox is not None
    assert len(removed) == 1
    assert removed[0].old_page == 2
    assert removed[0].old_bbox is not None


def test_modified_paragraph_keeps_both_anchors() -> None:
    new = _paper("n", "paper.pdf", [_block("b1", 3, MODIFIED_NEW)])
    old = _paper("o", "paper.pdf", [_block("b1", 3, MODIFIED_OLD)])
    changes = align_paragraphs(new, old)
    assert len(changes) == 1
    change = changes[0]
    assert change.kind == "modified"
    assert 0.35 <= change.similarity < 0.85
    assert change.new_page == 3 and change.old_page == 3
    assert change.new_bbox is not None and change.old_bbox is not None


def test_every_change_has_a_page_on_at_least_one_side() -> None:
    new = _paper(
        "n",
        "paper.pdf",
        [
            _block("b1", 1, IDENTICAL),
            _block("b2", 2, MODIFIED_NEW),
            _block(
                "b3",
                3,
                "we added a completely new paragraph about the evaluation protocol",
            ),
        ],
    )
    old = _paper(
        "o",
        "paper.pdf",
        [
            _block("b1", 1, IDENTICAL),
            _block("b2", 2, MODIFIED_OLD),
            _block(
                "b4",
                4,
                "the old paragraph about the baseline system has been removed",
            ),
        ],
    )
    for change in align_paragraphs(new, old):
        assert change.new_page is not None or change.old_page is not None


def test_build_diff_reports_whole_similarity() -> None:
    new = _paper("n", "paper.pdf", [_block("b1", 1, IDENTICAL)])
    old = _paper("o", "paper.pdf", [_block("b1", 1, IDENTICAL)])
    response = build_diff(new, old)
    assert response.new_id == "n" and response.old_id == "o"
    assert response.similarity == pytest.approx(whole_similarity(new, old))
    assert response.changes == []


def test_fallback_summary_counts_each_kind() -> None:
    from app.models.schemas import VersionChange

    changes = [
        VersionChange(kind="added", new_page=2, new_text="new paragraph"),
        VersionChange(kind="removed", old_page=3, old_text="old paragraph"),
        VersionChange(
            kind="modified",
            new_page=4,
            old_page=4,
            new_text=MODIFIED_NEW,
            old_text=MODIFIED_OLD,
            similarity=0.4,
        ),
    ]
    summary = _fallback_summary(changes)
    assert "新增段落：1 处" in summary
    assert "删除段落：1 处" in summary
    assert "改写段落：1 处" in summary
    assert "[新版 p.2]" in summary and "[旧版 p.3]" in summary


def test_summary_page_validation_rejects_fabricated_pages() -> None:
    from app.models.schemas import VersionChange

    changes = [VersionChange(kind="added", new_page=7, new_text="x")]
    assert _summary_pages_valid("训练细节调整 [新版 p.7]。", changes)
    assert not _summary_pages_valid("训练细节调整 [新版 p.9]。", changes)
    assert not _summary_pages_valid("结果见 p.9。", changes)
    assert _summary_pages_valid("结果见 p.7。", changes)
