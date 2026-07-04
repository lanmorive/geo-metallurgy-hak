#!/usr/bin/env python3
"""Synthesis на фикстуре retrieved_context.json — markdown в stdout."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.schemas.api import RetrievedContext
from app.schemas.ontology import GraphEdge, GraphNode, RelationType
from app.synthesis.answerer import extract_contradictions, synthesize

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "retrieved_context.json"

QUERY = (
    "Какие методы обессоливания воды применялись при содержании сульфатов 200–300 мг/л "
    "и сухом остатке ≤ 1000 мг/дм³?"
)


def _load_context() -> RetrievedContext:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    nodes = [GraphNode.model_validate(n) for n in data.get("nodes", [])]
    edges = []
    for e in data.get("edges", []):
        edge_data = dict(e)
        edge_data["type"] = RelationType(edge_data["type"])
        edges.append(GraphEdge.model_validate(edge_data))
    return RetrievedContext(
        chunks=data.get("chunks", []),
        cypher_results=data.get("cypher_results", []),
        nodes=nodes,
        edges=edges,
    )


async def main() -> int:
    ctx = _load_context()
    contradictions = extract_contradictions(ctx)
    print("=== Contradictions from fixture ===")
    for c in contradictions:
        print(f"- {c.source_a} vs {c.source_b}: {c.description}")

    print("\n=== Synthesized answer ===\n")
    answer = await synthesize(QUERY, ctx)
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
