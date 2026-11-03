"""Academic discovery adapters: arXiv Atom API and OpenAlex JSON API."""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree as ET

import httpx

from app.models.schemas import DiscoveryHit
from app.store import paper_store

logger = logging.getLogger(__name__)

ATOM = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.\-/]+")


async def search(query: str, source: str = "arxiv", limit: int = 10) -> list[DiscoveryHit]:
    if source == "openalex":
        return await search_openalex(query, limit)
    return await search_arxiv(query, limit)


async def search_arxiv(query: str, limit: int = 10) -> list[DiscoveryHit]:
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://export.arxiv.org/api/query", params=params)
        response.raise_for_status()
    root = ET.fromstring(response.text)
    hits: list[DiscoveryHit] = []
    for entry in root.findall("a:entry", ATOM):
        title = _text(entry.find("a:title", ATOM))
        abstract = _text(entry.find("a:summary", ATOM))
        authors = [
            _text(author.find("a:name", ATOM))
            for author in entry.findall("a:author", ATOM)
        ]
        published = _text(entry.find("a:published", ATOM))
        year = int(published[:4]) if published[:4].isdigit() else None
        url = _text(entry.find("a:id", ATOM))
        arxiv_id = url.rsplit("/abs/", 1)[-1] if "/abs/" in url else None
        doi = _text(entry.find("arxiv:doi", ATOM)) or None
        github_match = GITHUB_RE.search(abstract)
        hits.append(
            DiscoveryHit(
                source="arxiv",
                title=title,
                authors=authors,
                year=year,
                abstract=abstract,
                url=url,
                doi=doi,
                arxiv_id=arxiv_id,
                github_url=github_match.group() if github_match else None,
                reason="arXiv 主题相关",
            )
        )
    return hits


async def search_openalex(query: str, limit: int = 10) -> list[DiscoveryHit]:
    params = {
        "search": query,
        "per-page": limit,
        "sort": "relevance_score:desc",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://api.openalex.org/works", params=params)
        response.raise_for_status()
    payload = response.json()
    hits: list[DiscoveryHit] = []
    for work in payload.get("results", []):
        hits.append(
            DiscoveryHit(
                source="openalex",
                title=work.get("display_name") or "Untitled",
                authors=[
                    authorship.get("author", {}).get("display_name", "")
                    for authorship in work.get("authorships", [])
                    if authorship.get("author")
                ],
                year=work.get("publication_year"),
                abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
                url=work.get("id"),
                doi=(work.get("doi") or "").replace("https://doi.org/", "") or None,
                reason="OpenAlex 引用/主题相关",
            )
        )
    return hits


async def recommend(paper_ids: list[str], limit: int = 8) -> list[DiscoveryHit]:
    """A lightweight recommendation: use library titles as the query."""

    titles = [
        paper.title
        for paper_id in paper_ids
        if (paper := paper_store.get(paper_id)) is not None
    ]
    query = " ".join(title for title in titles if title) or "large language model research"
    hits = await search_arxiv(query, limit)
    for hit in hits:
        hit.reason = "与库中论文主题相近" + ("；含 GitHub 复现代码" if hit.github_url else "")
    return hits


def _text(element: ET.Element | None) -> str:
    return "".join(element.itertext()).strip() if element is not None else ""


def _reconstruct_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            positioned.append((position, word))
    positioned.sort()
    return " ".join(word for _position, word in positioned)
