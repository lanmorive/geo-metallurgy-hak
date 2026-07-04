#!/usr/bin/env python3
"""Прогон 4 эталонных запросов против живого графа с диагностикой."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.graph.driver import close_driver
from app.retrieval import embedder, hybrid
from app.retrieval.cypher_diagnostics import diagnose_empty_cypher
from app.retrieval.hybrid import RetrievalStats
from app.schemas.api import RetrievedContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

VECTOR_RELEVANCE_MIN_SCORE = 0.3
QUERY_TRUNC = 50
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "ref_runs"

REFERENCE_CASES: list[tuple[str, dict[str, Any]]] = [
    (
        "Какие методы обессоливания воды применялись при содержании сульфатов 200–300 мг/л "
        "и сухом остатке ≤ 1000 мг/дм³? Приведи источники и условия.",
        {},
    ),
    (
        "Найди эксперименты по кучному выщелачиванию никелевых руд в России после 2015 года.",
        {},
    ),
    (
        "Какие режимы обработки влияют на извлечение меди при флотации? "
        "Где источники противоречат друг другу?",
        {},
    ),
    (
        "Кто в компании / в литературе занимался очисткой сточных вод от сульфатов? "
        "Какие у них публикации?",
        {},
    ),
]


def _truncate(text: str, n: int = QUERY_TRUNC) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= n:
        return collapsed
    return collapsed[: n - 1] + "…"


def _top_chunks(ctx: RetrievedContext | None, limit: int = 5) -> list[dict[str, Any]]:
    if ctx is None:
        return []
    result: list[dict[str, Any]] = []
    for chunk in ctx.chunks[:limit]:
        result.append(
            {
                "title": chunk.get("title") or chunk.get("doc_id") or "",
                "score": chunk.get("score"),
            }
        )
    return result


def _numeric_facts(ctx: RetrievedContext | None) -> list[dict[str, Any]]:
    if ctx is None:
        return []
    facts: list[dict[str, Any]] = []
    for row in ctx.cypher_results:
        fact: dict[str, Any] = {"parameter": row.get("parameter")}
        if row.get("value") is not None:
            fact["value"] = row.get("value")
        if row.get("value_min") is not None:
            fact["value_min"] = row.get("value_min")
        if row.get("value_max") is not None:
            fact["value_max"] = row.get("value_max")
        if row.get("unit") is not None:
            fact["unit"] = row.get("unit")
        facts.append(fact)
    return facts


def verdict(cypher_rows: int, top_chunks: list[dict[str, Any]]) -> str:
    vector_ok = bool(top_chunks) and float(top_chunks[0].get("score") or 0) >= VECTOR_RELEVANCE_MIN_SCORE
    if cypher_rows > 0 or vector_ok:
        return "OK"
    return "FAIL"


def _print_diagnostics(diag: dict[str, Any]) -> None:
    print("  === Cypher diagnostics ===")
    if diag.get("term_counts"):
        print("  name_norm terms:")
        for entry in diag["term_counts"]:
            print(f"    {entry['term']!r}: {entry['count']} nodes")
    else:
        print("  name_norm terms: (none extracted from WHERE)")
    if diag.get("rel_counts"):
        print("  relationship types:")
        for entry in diag["rel_counts"]:
            print(f"    {entry['type']}: {entry['count']} edges")
    else:
        print("  relationship types: (none extracted)")
    for err in diag.get("errors") or []:
        print(f"  error: {err}")


def _print_query_result(i: int, result: dict[str, Any]) -> None:
    print(f"\n--- Query {i} ---")
    print(result["query"][:120] + ("..." if len(result["query"]) > 120 else ""))
    print(f"filters: {result['filters']}")
    print(f"mode: {result['mode']}")
    print(f"took_ms: {result['took_ms']}")
    if result.get("error"):
        print(f"error: {result['error']}")
    print(f"cypher_valid: {result['cypher_valid']}")
    if result.get("cypher_explanation"):
        print(f"explanation: {result['cypher_explanation']}")
    if result.get("cypher"):
        print(f"cypher:\n{result['cypher']}")
    print(f"cypher_rows: {result['cypher_rows']}")
    print(f"vector_hits: {result['vector_hits']}")
    print(
        f"vector_ms: {result['vector_ms']} (embed_ms: {result.get('embed_ms')} "
        f"search_ms: {result.get('search_ms')})  cypher_ms: {result['cypher_ms']}"
    )
    print("top_chunks:")
    for j, ch in enumerate(result.get("top_chunks") or [], 1):
        score = ch.get("score")
        score_s = f"{score:.4f}" if isinstance(score, int | float) else str(score)
        print(f"  {j}. {ch.get('title', '')} (score={score_s})")
    print(f"graph_nodes: {result['graph_nodes']}")
    if result.get("numeric_facts"):
        print("numeric_facts:")
        for fact in result["numeric_facts"]:
            print(f"  {fact}")
    print(f"verdict: {result['verdict']}")
    if result.get("cypher_diagnostics"):
        _print_diagnostics(result["cypher_diagnostics"])


def _print_summary_table(summary: list[dict[str, Any]]) -> None:
    print("\n=== Summary ===")
    header = f"| {'#':>2} | {'query':<{QUERY_TRUNC}} | cypher_rows | vector_hits | graph_nodes | verdict |"
    sep = f"|{'-'*4}|{'-'*(QUERY_TRUNC+2)}|{'-'*13}|{'-'*13}|{'-'*13}|{'-'*9}|"
    print(header)
    print(sep)
    for row in summary:
        print(
            f"| {row['index']:>2} "
            f"| {row['query_trunc']:<{QUERY_TRUNC}} "
            f"| {row['cypher_rows']:>11} "
            f"| {row['vector_hits']:>11} "
            f"| {row['graph_nodes']:>11} "
            f"| {row['verdict']:>7} |"
        )


async def run_one(query: str, filters: dict[str, Any]) -> dict[str, Any]:
    stats = RetrievalStats()
    ctx: RetrievedContext | None = None
    mode = "error"
    error: str | None = None
    cypher_diagnostics: dict[str, Any] | None = None

    t0 = time.perf_counter()
    try:
        ctx, mode = await hybrid.retrieve(query, filters, top_k=12, stats=stats)
    except Exception as exc:
        error = str(exc)
        logger.exception("reference query failed: %s", _truncate(query, 60))
    took_ms = int((time.perf_counter() - t0) * 1000)

    top = _top_chunks(ctx)
    if (
        error is None
        and stats.cypher_valid
        and stats.cypher_rows == 0
        and stats.cypher
    ):
        try:
            cypher_diagnostics = diagnose_empty_cypher(stats.cypher)
        except Exception as exc:
            cypher_diagnostics = {"errors": [str(exc)], "term_counts": [], "rel_counts": []}

    v = verdict(stats.cypher_rows, top) if error is None else "FAIL"

    return {
        "query": query,
        "filters": filters,
        "mode": mode,
        "took_ms": took_ms,
        "cypher": stats.cypher,
        "cypher_valid": stats.cypher_valid,
        "cypher_explanation": stats.cypher_explanation,
        "cypher_rows": stats.cypher_rows,
        "vector_hits": stats.vector_hits,
        "vector_ms": stats.vector_ms,
        "embed_ms": stats.embed_ms,
        "search_ms": stats.search_ms,
        "cypher_ms": stats.cypher_ms,
        "top_chunks": top,
        "graph_nodes": len(ctx.nodes) if ctx else 0,
        "numeric_facts": _numeric_facts(ctx),
        "verdict": v,
        "error": error,
        "cypher_diagnostics": cypher_diagnostics,
    }


async def main() -> int:
    if not settings.feature_graph:
        logger.warning("FEATURE_GRAPH=false — graph leg disabled; results may be vector-only")

    logger.info("Warming up embedding model...")
    t_warmup = time.perf_counter()
    await asyncio.to_thread(embedder.warmup)
    logger.info("Embedding model ready in %d ms", int((time.perf_counter() - t_warmup) * 1000))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_at = datetime.now(timezone.utc)
    timestamp = run_at.strftime("%Y%m%dT%H%M%S")

    results: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    fatal = False

    for i, (query, filters) in enumerate(REFERENCE_CASES, 1):
        try:
            result = await run_one(query, filters)
        except Exception as exc:
            fatal = True
            result = {
                "query": query,
                "filters": filters,
                "mode": "error",
                "took_ms": 0,
                "cypher": None,
                "cypher_valid": False,
                "cypher_explanation": "",
                "cypher_rows": 0,
                "vector_hits": 0,
                "vector_ms": 0,
                "cypher_ms": 0,
                "top_chunks": [],
                "graph_nodes": 0,
                "numeric_facts": [],
                "verdict": "FAIL",
                "error": str(exc),
                "cypher_diagnostics": None,
            }
            logger.exception("unhandled error on query %d", i)
        results.append(result)
        summary.append(
            {
                "index": i,
                "query_trunc": _truncate(query),
                "cypher_rows": result["cypher_rows"],
                "vector_hits": result["vector_hits"],
                "graph_nodes": result["graph_nodes"],
                "verdict": result["verdict"],
            }
        )
        _print_query_result(i, result)

    _print_summary_table(summary)

    payload = {
        "run_at": run_at.isoformat(),
        "feature_graph": settings.feature_graph,
        "feature_synthesis": settings.feature_synthesis,
        "results": results,
        "summary": summary,
    }
    out_path = OUTPUT_DIR / f"{timestamp}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {out_path}")

    return 1 if fatal else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    finally:
        close_driver()
