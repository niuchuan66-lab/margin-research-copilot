"""Citation graph construction and cornerstone-node mining."""

from __future__ import annotations

import hashlib
import logging
import uuid

from app.models.schemas import GraphEdge, GraphNode, GraphResponse, Paper
from app.services.dedup import normalize

logger = logging.getLogger(__name__)

_graphs: dict[str, GraphResponse] = {}


def build_citation_graph(papers: list[Paper]) -> GraphResponse:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    title_to_id: dict[str, str] = {}

    for paper in papers:
        nodes[paper.id] = GraphNode(
            id=paper.id,
            title=paper.title or paper.filename,
            year=_year(paper),
        )
        if paper.title:
            title_to_id[normalize(paper.title)] = paper.id

    for paper in papers:
        for reference in paper.references:
            target = _match_reference(reference, papers, title_to_id)
            if target is None and reference.title:
                target = f"ref:{hashlib.sha1(reference.title.encode()).hexdigest()[:10]}"
                nodes.setdefault(
                    target,
                    GraphNode(
                        id=target,
                        title=reference.title[:180],
                        year=reference.year,
                    ),
                )
            if target and target != paper.id:
                edges.append(GraphEdge(source=paper.id, target=target))

    edges = _dedupe_edges(edges)
    in_degree = {node_id: 0 for node_id in nodes}
    for edge in edges:
        in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

    centrality, algorithm = _centrality(nodes, edges, in_degree)
    for node_id, node in nodes.items():
        node.citations = in_degree.get(node_id, 0)
        node.centrality = round(centrality.get(node_id, 0.0), 6)

    ranked = sorted(
        nodes.values(),
        key=lambda node: (node.centrality, node.citations),
        reverse=True,
    )
    cornerstone_count = max(1, len(ranked) // 5) if ranked else 0
    for node in ranked[:cornerstone_count]:
        node.is_cornerstone = node.citations > 0 or node.centrality > 0

    cornerstone_titles = [node.title for node in ranked[:3] if node.is_cornerstone]
    summary = f"共 {len(nodes)} 个节点、{len(edges)} 条引用边；算法：{algorithm}。"
    if cornerstone_titles:
        summary += "基石论文：" + "、".join(cornerstone_titles) + "。"

    graph = GraphResponse(
        graph_id=uuid.uuid4().hex[:12],
        nodes=list(nodes.values()),
        edges=edges,
        algorithm=algorithm,
        summary=summary,
    )
    _graphs[graph.graph_id] = graph
    return graph


def get_graph(graph_id: str) -> GraphResponse | None:
    return _graphs.get(graph_id)


def _match_reference(reference, papers: list[Paper], title_to_id: dict[str, str]) -> str | None:
    if reference.doi:
        wanted = reference.doi.lower()
        for paper in papers:
            if str(paper.metadata.get("doi", "")).lower() == wanted:
                return paper.id
    if not reference.title:
        return None
    key = normalize(reference.title)
    if not key:
        return None
    if key in title_to_id:
        return title_to_id[key]
    for title, paper_id in title_to_id.items():
        if len(key) > 20 and (key in title or title in key):
            return paper_id
    return None


def _dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: set[tuple[str, str]] = set()
    unique: list[GraphEdge] = []
    for edge in edges:
        key = (edge.source, edge.target)
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
    return unique


def _centrality(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    in_degree: dict[str, int],
) -> tuple[dict[str, float], str]:
    try:
        import networkx as nx

        graph = nx.DiGraph()
        graph.add_nodes_from(nodes)
        for edge in edges:
            graph.add_edge(edge.source, edge.target, weight=edge.weight)
        if graph.number_of_nodes() == 0:
            return {}, "pagerank"
        return dict(nx.pagerank(graph)), "pagerank"
    except Exception as exc:
        logger.info("NetworkX PageRank unavailable (%s); using pure Python", exc)
        return _pure_pagerank(nodes, edges), "pagerank (pure python)"


def _pure_pagerank(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    damping: float = 0.85,
    iterations: int = 40,
) -> dict[str, float]:
    total = len(nodes)
    if total == 0:
        return {}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        if edge.source in outgoing and edge.target in nodes:
            outgoing[edge.source].append(edge.target)
    ranks = {node_id: 1.0 / total for node_id in nodes}
    for _ in range(iterations):
        next_ranks = {node_id: (1.0 - damping) / total for node_id in nodes}
        dangling = sum(
            ranks[node_id] for node_id, targets in outgoing.items() if not targets
        )
        for node_id, targets in outgoing.items():
            if not targets:
                continue
            share = damping * ranks[node_id] / len(targets)
            for target in targets:
                next_ranks[target] += share
        if dangling:
            bonus = damping * dangling / total
            for node_id in next_ranks:
                next_ranks[node_id] += bonus
        ranks = next_ranks
    return ranks


def _year(paper: Paper) -> int | None:
    value = paper.metadata.get("year")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
