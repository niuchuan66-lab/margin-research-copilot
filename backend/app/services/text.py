"""Small text utilities shared by retrieval and extractive answering."""

from __future__ import annotations

import re

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "were",
    "was",
    "are",
    "how",
    "many",
    "much",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "why",
    "when",
    "where",
    "used",
    "use",
    "using",
    "into",
    "over",
    "all",
    "its",
    "their",
    "our",
    "your",
    "you",
    "not",
    "but",
    "can",
    "has",
    "have",
    "had",
    "will",
    "would",
    "could",
    "should",
    "about",
    "than",
    "then",
    "also",
    "such",
    "may",
    "might",
    "must",
    "been",
    "being",
    "more",
    "most",
    "some",
    "any",
    "each",
    "other",
    "only",
    "own",
    "same",
    "too",
    "very",
    "just",
    "now",
    "new",
    "one",
    "two",
    "three",
    "does",
    "did",
    "doing",
    "there",
    "these",
    "those",
    "they",
    "them",
    "his",
    "her",
    "它",
    "的",
    "了",
    "和",
    "是",
    "在",
    "有",
    "与",
    "及",
    "对",
    "为",
    "中",
}


def keywords(text: str) -> list[str]:
    normalized = text.lower()
    normalized = re.sub(r"beta\s*1", "β1", normalized)
    normalized = re.sub(r"beta\s*2", "β2", normalized)
    words = re.findall(r"[a-zA-Z0-9βγ]+", normalized)
    kept: list[str] = []
    for word in words:
        if len(word) > 2 and word not in STOPWORDS:
            kept.append(word)
        elif len(word) == 2 and any(ch.isdigit() or ch in "βγ" for ch in word):
            kept.append(word)
    return kept


def best_window(text: str, query: str, width: int = 420) -> str:
    """Return the densest query-related slice of a long block."""

    if len(text) <= width:
        return text
    terms = keywords(query)
    if not terms:
        return text[:width]
    lowered = text.lower()
    hits: list[int] = []
    for term in terms:
        start = 0
        while True:
            index = lowered.find(term, start)
            if index < 0:
                break
            hits.append(index)
            start = index + 1
    if not hits:
        return text[:width]
    hits.sort()
    if hits[-1] - hits[0] <= width:
        start = max(0, hits[0] - 60)
        return text[start : start + width].strip()
    best_position = hits[0]
    best_count = 0
    for position in hits:
        count = sum(1 for hit in hits if position <= hit < position + width)
        if count > best_count:
            best_count = count
            best_position = position
    start = max(0, min(best_position - width // 4, len(text) - width))
    return text[start : start + width].strip()
