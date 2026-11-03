from __future__ import annotations

from app.services.dedup import compare, jaccard, shingles


def _paper_text() -> str:
    return " ".join(
        ["attention is all you need transformer encoder decoder self attention"] * 30
    )


def test_same_content_is_duplicate_and_keeps_newer() -> None:
    result = compare(
        _paper_text(),
        "1706.03762v1.pdf",
        [("p1", "1706.03762v7.pdf", _paper_text())],
    )
    assert result.is_duplicate is True
    assert result.action == "keep"
    assert result.candidates[0].newer_version is False


def test_uploading_newer_version_replaces() -> None:
    result = compare(
        _paper_text(),
        "1706.03762v7.pdf",
        [("p1", "1706.03762v1.pdf", _paper_text())],
    )
    assert result.is_duplicate is True
    assert result.action == "replace"
    assert result.candidates[0].newer_version is True


def test_unrelated_text_is_not_duplicate() -> None:
    result = compare(
        "graph neural networks for molecules and property prediction",
        "gnn.pdf",
        [("p1", "transformer.pdf", _paper_text())],
    )
    assert result.is_duplicate is False
    assert result.action in {"accept", "warn"}


def test_jaccard_bounds() -> None:
    left = shingles("a b c d e f g")
    assert jaccard(left, left) == 1.0
    assert jaccard(left, shingles("x y z")) == 0.0
