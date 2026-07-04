#!/usr/bin/env python3
"""Отчёт о качестве графа Neo4j после загрузки."""

from __future__ import annotations

import logging
import sys
from typing import Any

from app.graph.convert import ENTITY_LABELS
from app.graph.driver import close_driver, get_driver
from app.graph.quality import find_duplicate_pairs
from app.graph.stop_entities import is_suspicious_name_norm, load_stop_entities

logger = logging.getLogger(__name__)

ALL_ENTITY_LABELS = ENTITY_LABELS
DEGREE_TOP_N = 30
SUSPICIOUS_LIST_CAP = 50


def _run_query(cypher: str, **params: Any) -> list[dict[str, Any]]:
    driver = get_driver()
    with driver.session() as session:
        return [dict(record) for record in session.run(cypher, **params)]


def print_counters() -> None:
    print("=== 1. Counters ===")
    print("\nNodes by label:")
    for label in ALL_ENTITY_LABELS:
        rows = _run_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")
        print(f"  {label}: {rows[0]['cnt'] if rows else 0}")
    for label in ("Publication", "Chunk"):
        rows = _run_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")
        print(f"  {label}: {rows[0]['cnt'] if rows else 0}")

    print("\nEdges by type:")
    rows = _run_query(
        "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS cnt ORDER BY cnt DESC"
    )
    for row in rows:
        print(f"  {row['rel_type']}: {row['cnt']}")

    coverage = _run_query(
        """
        MATCH (pub:Publication)
        OPTIONAL MATCH (e)-[:DESCRIBED_IN]->(pub)
        WHERE any(l IN labels(e) WHERE l IN $entity_labels)
        WITH pub, count(DISTINCT e) AS entity_count
        RETURN count(pub) AS total,
               sum(CASE WHEN entity_count >= 1 THEN 1 ELSE 0 END) AS with_entities
        """,
        entity_labels=ALL_ENTITY_LABELS,
    )
    if coverage:
        total = coverage[0]["total"]
        with_entities = coverage[0]["with_entities"]
        pct = (100.0 * with_entities / total) if total else 0.0
        print(f"\nPublication coverage: {with_entities}/{total} ({pct:.1f}%) have >= 1 linked entity")


def print_suspicious(stop_set: frozenset[str]) -> None:
    print("\n=== 2. Suspicious ===")

    print("\nTop-30 entities by degree (per label):")
    for label in ALL_ENTITY_LABELS:
        rows = _run_query(
            f"""
            MATCH (n:{label})
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) AS degree
            ORDER BY degree DESC
            LIMIT $limit
            RETURN n.name_norm AS name_norm, degree
            """,
            limit=DEGREE_TOP_N,
        )
        if not rows:
            continue
        print(f"\n  [{label}]")
        for row in rows:
            print(f"    {row['name_norm']}\tdegree={row['degree']}")

    stop_list = sorted(stop_set)
    stop_rows = _run_query(
        """
        MATCH (n)
        WHERE n.name_norm IN $stop
          AND any(l IN labels(n) WHERE l IN $entity_labels)
        RETURN labels(n)[0] AS label, n.name_norm AS name_norm
        ORDER BY label, name_norm
        """,
        stop=stop_list,
        entity_labels=ALL_ENTITY_LABELS,
    )
    print(f"\nStop-list entities in graph: {len(stop_rows)}")
    for row in stop_rows:
        print(f"  {row['label']}: {row['name_norm']}")

    all_names = _run_query(
        """
        MATCH (n)
        WHERE any(l IN labels(n) WHERE l IN $entity_labels)
        RETURN labels(n)[0] AS label, n.name_norm AS name_norm
        """,
        entity_labels=ALL_ENTITY_LABELS,
    )
    suspicious = [
        (row["label"], row["name_norm"])
        for row in all_names
        if is_suspicious_name_norm(row["name_norm"])
    ]
    print(f"\nSuspicious name_norm (short/OCR): {len(suspicious)}")
    for label, name_norm in suspicious[:SUSPICIOUS_LIST_CAP]:
        print(f"  {label}: {name_norm}")
    if len(suspicious) > SUSPICIOUS_LIST_CAP:
        print(f"  ... and {len(suspicious) - SUSPICIOUS_LIST_CAP} more")

    orphan_rows = _run_query(
        """
        MATCH (p:Property)
        WHERE NOT (p)<-[:HAS_PROPERTY|OPERATES_AT_CONDITION]-()
        RETURN count(p) AS cnt, collect(p.name_norm)[..30] AS examples
        """
    )
    if orphan_rows:
        print(f"\nOrphan Property nodes (no numeric edge): {orphan_rows[0]['cnt']}")
        for name in orphan_rows[0]["examples"] or []:
            print(f"  {name}")


def print_edge_sample() -> None:
    print("\n=== 3. Edge sample (HAS_PROPERTY / OPERATES_AT_CONDITION) ===")
    rows = _run_query(
        """
        MATCH (src)-[r:HAS_PROPERTY|OPERATES_AT_CONDITION]->(dst:Property)
        WHERE r.value IS NOT NULL AND r.unit IS NOT NULL AND trim(r.unit) <> ''
        WITH src, r
        ORDER BY rand()
        LIMIT 10
        RETURN labels(src)[0] AS entity_label,
               src.name_norm AS entity,
               r.parameter AS parameter,
               r.operator AS operator,
               r.value AS value,
               r.unit AS unit,
               r.source_doc AS source_doc,
               r.source_chunk AS source_chunk
        """
    )
    if not rows:
        print("  (no valid numeric edges found)")
        return
    header = (
        "entity_label",
        "entity",
        "parameter",
        "operator",
        "value",
        "unit",
        "source_doc",
        "source_chunk",
    )
    print("\t".join(header))
    for row in rows:
        print(
            "\t".join(
                str(row.get(k, ""))
                for k in (
                    "entity_label",
                    "entity",
                    "parameter",
                    "operator",
                    "value",
                    "unit",
                    "source_doc",
                    "source_chunk",
                )
            )
        )


def print_duplicates() -> None:
    print("\n=== 4. Duplicate candidates (token_sort_ratio > 90) ===")
    names_by_label: dict[str, list[str]] = {}
    for label in ALL_ENTITY_LABELS:
        rows = _run_query(
            f"MATCH (n:{label}) RETURN n.name_norm AS name_norm"
        )
        names_by_label[label] = [row["name_norm"] for row in rows if row.get("name_norm")]

    pairs = find_duplicate_pairs(names_by_label)
    if not pairs:
        print("  (no pairs above threshold)")
        return
    for pair in pairs:
        print(f"  [{pair.label}] {pair.score:.1f}  {pair.name_a}  <->  {pair.name_b}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stop_set = load_stop_entities()
    try:
        print_counters()
        print_suspicious(stop_set)
        print_edge_sample()
        print_duplicates()
    finally:
        close_driver()
    return 0


if __name__ == "__main__":
    sys.exit(main())
