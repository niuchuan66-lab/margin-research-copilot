"""Content-based deduplication and arXiv-style version heuristics."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.schemas import DedupCandidate, DedupResult

_VERSION_RE = re.compile(r"v(\d+)", re.IGNORECASE)


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9一-鿿]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def shingles(text: str, size: int = 5) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    if len(words) <= size:
        return {tuple(words)} if words else set()
    return {tuple(words[index : index + size]) for index in range(len(words) - size + 1)}


def jaccard(left: set[tuple[str, ...]], right: set[tuple[str, ...]]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _version(filename: str | None) -> int | None:
    if not filename:
        return None
    match = _VERSION_RE.search(filename)
    return int(match.group(1)) if match else None


def compare(
    new_text: str,
    new_filename: str,
    candidates: Sequence[tuple[str, str | None, str]],
) -> DedupResult:
    """Compare a new paper against (paper_id, title, text) candidates."""

    new_shingles = shingles(new_text)
    best_similarity = 0.0
    best_candidate: DedupCandidate | None = None

    for paper_id, title, text in candidates:
        if not text.strip():
            continue
        similarity = jaccard(new_shingles, shingles(text))
        if similarity <= best_similarity:
            continue
        new_version = _version(new_filename)
        old_version = _version(title or "")
        newer = (
            new_version is not None
            and old_version is not None
            and new_version > old_version
        )
        reason = (
            "正文高度重合"
            if similarity >= 0.62
            else "存在较高重合片段，建议人工确认"
        )
        best_similarity = similarity
        best_candidate = DedupCandidate(
            paper_id=paper_id,
            title=title,
            similarity=round(similarity, 4),
            reason=reason,
            newer_version=newer,
        )

    if best_candidate is None:
        return DedupResult()

    is_duplicate = best_similarity >= 0.62
    action = "accept"
    if is_duplicate:
        action = "replace" if best_candidate.newer_version else "keep"
    elif best_similarity >= 0.45:
        action = "warn"

    return DedupResult(
        is_duplicate=is_duplicate,
        similarity=round(best_similarity, 4),
        action=action,
        candidates=[best_candidate],
    )
