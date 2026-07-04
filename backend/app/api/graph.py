"""GET /api/graph/* — подграф и статистика для визуализации."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.graph.convert import (
    ALL_NODE_LABELS,
    ENTITY_LABELS,
    records_to_subset,
)
from app.graph.driver import get_driver
from app.schemas.api import GraphStatsResponse, GraphSubset, SubgraphResponse

logger = logging.getLogger(__name__)
router = APIRouter()

SKIP_EXPANSION_REL_TYPES = {"part_of", "DESCRIBED_IN"}

_STATS_CYPHER = """
MATCH (n)
RETURN
  sum(CASE WHEN any(l IN labels(n) WHERE l IN $entity_labels) THEN 1 ELSE 0 END) AS entities,
  sum(CASE WHEN n:Chunk THEN 1 ELSE 0 END) AS chunks,
  sum(CASE WHEN n:Publication THEN 1 ELSE 0 END) AS publications
"""

_PREVIEW_SUBGRAPH_CYPHER = """
MATCH (n)
WHERE any(l IN labels(n) WHERE l IN $entity_labels)
WITH n, count { (n)--() } AS degree
ORDER BY degree DESC
LIMIT $limit
WITH collect(n) AS seed
UNWIND seed AS n
OPTIONAL MATCH (n)-[r]-(m)
WHERE any(l IN labels(m) WHERE l IN $all_labels)
WITH collect(DISTINCT n) + collect(DISTINCT m) AS node_lists, collect(DISTINCT r) AS rels
UNWIND node_lists AS node
WITH collect(DISTINCT node)[..$limit] AS nodes, rels
WITH nodes, [rel IN rels WHERE startNode(rel) IN nodes AND endNode(rel) IN nodes] AS rels
RETURN nodes, rels
"""

_PUBLICATION_EXPERT_FALLBACK_CYPHER = """
MATCH (p:Publication)
WITH p
ORDER BY coalesce(p.year, 0) DESC, p.title
LIMIT $pub_limit
OPTIONAL MATCH (e:Expert)-[r]-(p)
WITH collect(DISTINCT p) + collect(DISTINCT e) AS node_lists, collect(DISTINCT r) AS rels
UNWIND node_lists AS node
WITH collect(DISTINCT node) AS nodes, rels
WITH nodes, [rel IN rels WHERE rel IS NOT NULL AND startNode(rel) IN nodes AND endNode(rel) IN nodes] AS rels
RETURN nodes, rels
"""

_CHUNK_ENTITY_EXPANSION_CYPHER = """
MATCH (c:Chunk)-[:part_of]->(p:Publication)<-[:DESCRIBED_IN]-(e)
WHERE c.chunk_id IN $chunk_ids
  AND any(l IN labels(e) WHERE l IN $entity_labels)
  AND coalesce(e.confidence, 0.0) >= $min_confidence
WITH e, p, max(coalesce(e.confidence, 0.0)) AS confidence
ORDER BY confidence DESC
LIMIT $entity_limit
OPTIONAL MATCH (e)-[r]-(e2)
WHERE NOT type(r) IN $skip_rel_types
  AND any(l IN labels(e2) WHERE l IN $all_labels)
WITH collect(DISTINCT e) + collect(DISTINCT p) + collect(DISTINCT e2) AS node_lists,
     collect(DISTINCT r) AS rels
UNWIND node_lists AS node
WITH collect(DISTINCT node)[..$node_limit] AS nodes, rels
WITH nodes, [rel IN rels WHERE rel IS NOT NULL AND startNode(rel) IN nodes AND endNode(rel) IN nodes] AS rels
RETURN nodes, rels
"""


def _query_subset(cypher: str, **params: Any) -> GraphSubset:
    driver = get_driver()
    with driver.session() as session:
        record = session.run(cypher, **params).single()
    if record is None:
        return GraphSubset()
    return records_to_subset(list(record["nodes"] or []), list(record["rels"] or []))


def expand_chunks_1hop(chunk_ids: list[str], min_confidence: float) -> GraphSubset:
    if not chunk_ids:
        return GraphSubset()
    return _query_subset(
        _CHUNK_ENTITY_EXPANSION_CYPHER,
        chunk_ids=chunk_ids,
        min_confidence=min_confidence,
        entity_limit=45,
        node_limit=60,
        entity_labels=ENTITY_LABELS,
        all_labels=ALL_NODE_LABELS,
        skip_rel_types=list(SKIP_EXPANSION_REL_TYPES),
    )


def get_preview_subgraph(limit: int = 150) -> GraphSubset:
    limit = max(1, min(limit, 300))
    subset = _query_subset(
        _PREVIEW_SUBGRAPH_CYPHER,
        limit=limit,
        entity_labels=ENTITY_LABELS,
        all_labels=ALL_NODE_LABELS,
    )
    if subset.nodes:
        return subset
    return _query_subset(
        _PUBLICATION_EXPERT_FALLBACK_CYPHER,
        pub_limit=min(limit, 150),
    )


def get_graph_stats() -> GraphStatsResponse:
    driver = get_driver()
    with driver.session() as session:
        record = session.run(_STATS_CYPHER, entity_labels=ENTITY_LABELS).single()
    if record is None:
        return GraphStatsResponse()
    return GraphStatsResponse(
        entities=int(record["entities"] or 0),
        chunks=int(record["chunks"] or 0),
        publications=int(record["publications"] or 0),
    )


def filter_subset_by_node_ids(subset: GraphSubset, node_ids: list[str]) -> GraphSubset:
    if not node_ids:
        return subset
    wanted = set(node_ids)
    nodes = [node for node in subset.nodes if node.id in wanted]
    node_id_set = {node.id for node in nodes}
    edges = [
        edge
        for edge in subset.edges
        if edge.source in node_id_set and edge.target in node_id_set
    ]
    return GraphSubset(nodes=nodes, edges=edges)


@router.get("/graph/stats", response_model=GraphStatsResponse)
def stats() -> GraphStatsResponse:
    """Вернуть агрегированную статистику графа."""
    try:
        return get_graph_stats()
    except Exception as exc:
        logger.warning("graph stats unavailable: %s", exc)
        return GraphStatsResponse()


@router.get("/graph/subgraph", response_model=SubgraphResponse)
def subgraph(
    node_ids: list[str] = Query(default=[]),
    limit: int = Query(default=150, ge=1, le=300),
) -> SubgraphResponse:
    """
    Вернуть подграф для react-force-graph-2d.

    Args:
        node_ids: Опциональный список id узлов для фильтрации.
    """
    logger.info("subgraph node_ids=%s limit=%s", node_ids, limit)
    try:
        subset = get_preview_subgraph(limit=limit)
        subset = filter_subset_by_node_ids(subset, node_ids)
        return SubgraphResponse(nodes=subset.nodes, edges=subset.edges, mock=False)
    except Exception as exc:
        logger.warning("subgraph unavailable: %s", exc)
        return SubgraphResponse(mock=False)
