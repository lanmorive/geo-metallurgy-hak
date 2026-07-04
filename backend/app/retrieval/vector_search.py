"""Vector search over Chunk embeddings in Neo4j."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

from app.graph.driver import close_driver, get_driver
from app.retrieval.embedder import embed_query

logger = logging.getLogger(__name__)

_VECTOR_SEARCH = """
CALL db.index.vector.queryNodes('chunk_embedding', $overfetch, $qvec)
YIELD node, score
MATCH (node)-[:part_of]->(p:Publication)
WHERE NOT coalesce(node.is_reference, false)
  AND ($year_min IS NULL OR p.year >= $year_min)
  AND ($year_max IS NULL OR p.year <= $year_max)
  AND ($lang IS NULL OR p.lang = $lang)
  AND ($doc_type IS NULL OR p.doc_type = $doc_type)
RETURN node.chunk_id AS chunk_id,
       node.text AS text,
       score,
       p.doc_id AS doc_id,
       p.title AS title,
       node.page AS page,
       node.section AS section,
       p.year AS year,
       p.venue AS venue,
       p.doc_type AS doc_type,
       p.lang AS lang,
       p.geography AS geography
ORDER BY score DESC
LIMIT $k
"""


def _dedup_chunks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Схлопнуть чанки с одинаковым (doc_id, первые 120 символов text), оставив max score."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        key = (str(row.get("doc_id") or ""), (row.get("text") or "")[:120])
        current = best.get(key)
        if current is None:
            best[key] = row
            order.append(key)
        elif (row.get("score") or 0.0) > (current.get("score") or 0.0):
            best[key] = row
    return [best[key] for key in order]


def search_by_vector(
    qvec: list[float],
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
    close_after: bool = False,
) -> list[dict[str, Any]]:
    """Только Neo4j-поиск по готовому вектору (без эмбеддинга)."""
    filters = filters or {}
    # k*4 у индекса: запас на отсев библиографии (is_reference) и схлопывание дублей
    overfetch = top_k * 4

    params = {
        "qvec": qvec,
        "k": overfetch,
        "overfetch": overfetch,
        "year_min": filters.get("year_min"),
        "year_max": filters.get("year_max"),
        "lang": filters.get("lang"),
        "doc_type": filters.get("doc_type"),
    }

    driver = get_driver()
    t0 = time.perf_counter()
    try:
        with driver.session() as session:
            result = session.run(_VECTOR_SEARCH, **params)
            rows = [dict(record) for record in result]
    finally:
        if close_after:
            close_driver()
    deduped = _dedup_chunks(rows)[:top_k]
    logger.info(
        "vector search: %d hits -> %d after dedup in %d ms",
        len(rows),
        len(deduped),
        int((time.perf_counter() - t0) * 1000),
    )
    return deduped


def search(
    query: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
    close_after: bool = False,
) -> list[dict[str, Any]]:
    """Эмбеддинг запроса + Neo4j-поиск (для CLI и не-async вызовов)."""
    t0 = time.perf_counter()
    qvec = embed_query(query)
    logger.info("embed_query: %d ms", int((time.perf_counter() - t0) * 1000))
    return search_by_vector(qvec, top_k, filters, close_after)


def _print_results(results: list[dict[str, Any]]) -> None:
    for i, row in enumerate(results, 1):
        text = row.get("text") or ""
        snippet = text[:200].replace("\n", " ")
        print(f"\n{i}. score={row['score']:.4f}  {row.get('title', '')}")
        print(f"   doc={row.get('doc_id')}  page={row.get('page')}  section={row.get('section')}")
        print(f"   {snippet}...")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semantic search over document chunks")
    parser.add_argument("query", help="Search query text")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--year-min", type=int, default=None)
    parser.add_argument("--year-max", type=int, default=None)
    parser.add_argument("--lang", default=None)
    parser.add_argument("--doc-type", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    filters: dict[str, Any] = {}
    if args.year_min is not None:
        filters["year_min"] = args.year_min
    if args.year_max is not None:
        filters["year_max"] = args.year_max
    if args.lang:
        filters["lang"] = args.lang
    if args.doc_type:
        filters["doc_type"] = args.doc_type

    results = search(args.query, top_k=args.top_k, filters=filters, close_after=True)
    print(f"Query: {args.query!r}  ({len(results)} results)")
    _print_results(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
