"""Гибридный retrieval: слияние результатов через RRF."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from neo4j import READ_ACCESS

from app.config import settings
from app.graph.convert import (
    ENTITY_LABELS,
    build_publication_star,
    merge_subsets,
    records_to_subset,
)
from app.graph.driver import get_driver
from app.retrieval import text2cypher, vector_search
from app.retrieval.embedder import embed_query
from app.schemas.api import GraphSubset, RetrievedContext

logger = logging.getLogger(__name__)

RRF_K = 60
NODE_LIMIT = 60


@dataclass
class RetrievalStats:
    """Сырые метрики ног retrieval (для логов и диагностических скриптов)."""

    vector_hits: int = 0
    cypher_rows: int = 0
    vector_ms: int = 0
    embed_ms: int = 0
    search_ms: int = 0
    cypher_ms: int = 0
    cypher: str | None = None
    cypher_valid: bool = False
    cypher_explanation: str = ""


_CYPHER_SUBGRAPH = """
UNWIND $names AS item
MATCH (n)
WHERE n.name = item.name OR n.name_norm = item.name_norm
  AND any(l IN labels(n) WHERE l IN $entity_labels)
WITH collect(DISTINCT n) AS seed
UNWIND seed AS n
OPTIONAL MATCH (n)-[r]-(m)
WHERE any(l IN labels(m) WHERE l IN $entity_labels OR m:Publication)
WITH collect(DISTINCT n) + collect(DISTINCT m) AS node_lists, collect(DISTINCT r) AS rels
UNWIND node_lists AS node
WITH collect(DISTINCT node)[..$node_limit] AS nodes, rels
WITH nodes, [rel IN rels WHERE rel IS NOT NULL AND startNode(rel) IN nodes AND endNode(rel) IN nodes] AS rels
RETURN nodes, rels
"""


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    k: int = RRF_K,
    id_key: str = "id",
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion: score(d) = sum(1 / (k + rank(d))).
    """
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    for result_list in ranked_lists:
        for rank, item in enumerate(result_list, start=1):
            item_id = str(item.get(id_key, rank))
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            items[item_id] = item
    fused = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [{**items[item_id], "rrf_score": scores[item_id]} for item_id in fused]


def _is_numeric_row(row: dict[str, Any]) -> bool:
    return bool(row.get("parameter")) and (
        row.get("value") is not None
        or row.get("value_min") is not None
        or row.get("value_max") is not None
    )


def _doc_ids_from_cypher(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Построить ranked list doc_id из cypher results (порядок = rank)."""
    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for row in rows:
        sources = row.get("sources") or []
        if isinstance(sources, list):
            for src in sources:
                if isinstance(src, dict):
                    doc_id = str(src.get("doc_id") or "")
                    if doc_id and doc_id not in seen:
                        seen.add(doc_id)
                        ranked.append({"doc_id": doc_id, **src})
        doc_id = str(row.get("doc_id") or "")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            ranked.append({"doc_id": doc_id, "title": row.get("title"), "year": row.get("year")})
    return ranked


def _best_chunk_per_doc(
    vector_chunks: list[dict[str, Any]],
    fused_doc_ids: list[str],
    cypher_ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_doc: dict[str, dict[str, Any]] = {}
    for chunk in vector_chunks:
        doc_id = str(chunk.get("doc_id") or "")
        if doc_id and doc_id not in by_doc:
            by_doc[doc_id] = chunk

    cypher_by_doc = {str(r["doc_id"]): r for r in cypher_ranked if r.get("doc_id")}

    result: list[dict[str, Any]] = []
    for doc_id in fused_doc_ids:
        if doc_id in by_doc:
            result.append(by_doc[doc_id])
        elif doc_id in cypher_by_doc:
            src = cypher_by_doc[doc_id]
            result.append(
                {
                    "doc_id": doc_id,
                    "title": src.get("title") or doc_id,
                    "year": src.get("year"),
                    "text": "",
                    "score": 0.0,
                    "chunk_id": f"synthetic:{doc_id}",
                }
            )
    return result


def _entity_names_from_cypher(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    names: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        key = str(name).lower()
        if key in seen:
            continue
        seen.add(key)
        names.append({"name": str(name), "name_norm": str(name).lower()})
    return names[:20]


def _fetch_cypher_subgraph(names: list[dict[str, str]]) -> GraphSubset:
    if not names:
        return GraphSubset()
    driver = get_driver()
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            record = session.run(
                _CYPHER_SUBGRAPH,
                names=names,
                entity_labels=ENTITY_LABELS,
                node_limit=NODE_LIMIT,
                timeout=10.0,
            ).single()
        if record is None:
            return GraphSubset()
        return records_to_subset(list(record["nodes"] or []), list(record["rels"] or []))
    except Exception as exc:
        logger.warning("cypher subgraph fetch failed: %s", exc)
        return GraphSubset()


def _build_graph_subset(
    cypher_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> GraphSubset:
    pub_star = build_publication_star(chunks)
    entity_subset = _fetch_cypher_subgraph(_entity_names_from_cypher(cypher_rows))
    return merge_subsets(pub_star, entity_subset, max_nodes=NODE_LIMIT)


async def retrieve(
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 12,
    stats: RetrievalStats | None = None,
) -> tuple[RetrievedContext, str]:
    """
    Гибридный retrieval: vector + optional text2cypher с RRF и деградацией.

    Returns:
        (RetrievedContext, retrieval_mode) where mode is vector|graph|vector+graph.
    """
    filters = filters or {}
    vector_chunks: list[dict[str, Any]] = []
    cypher_rows: list[dict[str, Any]] = []
    vector_error: Exception | None = None
    graph_error: Exception | None = None
    vector_ms = 0
    embed_ms = 0
    search_ms = 0
    cypher_ms = 0

    async def _vector() -> list[dict[str, Any]]:
        nonlocal vector_ms, embed_ms, search_ms
        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        # embed_query — sync CPU-bound, уводим с event loop
        qvec = await loop.run_in_executor(None, embed_query, query)
        embed_ms = int((time.perf_counter() - t0) * 1000)
        t1 = time.perf_counter()
        result = await loop.run_in_executor(
            None, vector_search.search_by_vector, qvec, 20, filters
        )
        search_ms = int((time.perf_counter() - t1) * 1000)
        vector_ms = embed_ms + search_ms
        return result

    async def _graph() -> list[dict[str, Any]]:
        nonlocal cypher_ms
        if not settings.feature_graph:
            return []
        t0 = time.perf_counter()
        plan = await text2cypher.generate(query, filters)
        if stats is not None:
            stats.cypher = plan.cypher
            stats.cypher_valid = (
                text2cypher.validate_cypher(plan.cypher) if plan.cypher else False
            )
            stats.cypher_explanation = plan.explanation
        rows = await text2cypher.execute(plan)
        cypher_ms = int((time.perf_counter() - t0) * 1000)
        return rows

    vector_result, graph_result = await asyncio.gather(
        _vector(), _graph(), return_exceptions=True
    )

    if isinstance(vector_result, Exception):
        vector_error = vector_result
        logger.exception(
            "vector search failed in hybrid retrieve", exc_info=vector_result
        )
    else:
        vector_chunks = vector_result

    if isinstance(graph_result, Exception):
        graph_error = graph_result
        logger.exception(
            "text2cypher failed in hybrid retrieve", exc_info=graph_result
        )
    else:
        cypher_rows = graph_result

    if stats is not None:
        stats.vector_hits = len(vector_chunks) if vector_error is None else 0
        stats.cypher_rows = len(cypher_rows) if graph_error is None else 0
        stats.vector_ms = vector_ms
        stats.embed_ms = embed_ms
        stats.search_ms = search_ms
        stats.cypher_ms = cypher_ms

    vector_ok = vector_error is None and bool(vector_chunks)
    graph_ok = graph_error is None and bool(cypher_rows)

    if not vector_ok and not graph_ok:
        if vector_error and graph_error:
            raise RuntimeError("vector and graph retrieval both failed") from vector_error
        if vector_error:
            raise vector_error
        raise RuntimeError("no retrieval results")

    if vector_ok and graph_ok:
        mode = "vector+graph"
    elif vector_ok:
        mode = "vector"
    else:
        mode = "graph"

    cypher_ranked = _doc_ids_from_cypher(cypher_rows)
    vector_ranked = [{"doc_id": str(c.get("doc_id") or ""), **c} for c in vector_chunks if c.get("doc_id")]

    if vector_ok and graph_ok:
        fused = reciprocal_rank_fusion([vector_ranked, cypher_ranked], id_key="doc_id")
        fused_doc_ids = [str(item["doc_id"]) for item in fused[:top_k]]
        top_chunks = _best_chunk_per_doc(vector_chunks, fused_doc_ids, cypher_ranked)
    elif vector_ok:
        top_chunks = vector_chunks[:top_k]
    else:
        fused_doc_ids = [str(r["doc_id"]) for r in cypher_ranked[:top_k]]
        top_chunks = _best_chunk_per_doc([], fused_doc_ids, cypher_ranked)

    graph_subset = _build_graph_subset(cypher_rows, top_chunks)
    if not graph_subset.nodes and top_chunks:
        graph_subset = build_publication_star(top_chunks)

    ctx = RetrievedContext(
        chunks=top_chunks,
        cypher_results=[r for r in cypher_rows if _is_numeric_row(r)],
        nodes=graph_subset.nodes,
        edges=graph_subset.edges,
    )
    logger.info(
        "hybrid retrieve mode=%s vector_chunks=%d cypher_rows=%d "
        "embed_ms=%d search_ms=%d vector_ms=%d cypher_ms=%d chunks=%d facts=%d nodes=%d",
        mode,
        len(vector_chunks) if vector_error is None else 0,
        len(cypher_rows) if graph_error is None else 0,
        embed_ms,
        search_ms,
        vector_ms,
        cypher_ms,
        len(ctx.chunks),
        len(ctx.cypher_results),
        len(ctx.nodes),
    )
    return ctx, mode
