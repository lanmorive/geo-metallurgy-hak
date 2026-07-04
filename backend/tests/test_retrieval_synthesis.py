"""Unit tests for retrieval, text2cypher validation, gaps, synthesis fallback."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from neo4j import READ_ACCESS

from app.api import query as query_api
from app.main import app
from app.retrieval.text2cypher import normalize_cypher, validate_cypher
from app.schemas.api import QueryResponse, RetrievedContext
from app.schemas.ontology import GraphEdge, GraphNode, RelationType
from app.synthesis.answerer import build_synthesis_context, strip_invalid_citations
from app.synthesis.gaps import find_gaps

client = TestClient(app)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "retrieved_context.json"

EVIL_CYPHER = [
    ("SET n.x = 1", "SET"),
    ("MATCH (n) CALL apoc.path.expand(n)", "apoc"),
    ("MATCH (a)-[*]->(b) RETURN a", "unbounded path"),
    ("CALL db.labels() YIELD label RETURN label", "CALL"),
    ("MATCH (n) DELETE n", "DELETE"),
    ("LOAD CSV FROM 'file:///tmp/x.csv' AS row RETURN row", "LOAD CSV"),
]

INJECTION = "MATCH (n) DETACH DELETE n"


def test_validate_cypher_rejects_evil_strings() -> None:
    for cypher, _label in EVIL_CYPHER:
        assert validate_cypher(cypher) is False, cypher
    assert validate_cypher(INJECTION) is False


def test_validate_cypher_appends_limit() -> None:
    raw = "MATCH (n:Process) RETURN n.name AS name"
    normalized = normalize_cypher(raw)
    assert normalized is not None
    assert "LIMIT 50" in normalized.upper()


def test_validate_cypher_accepts_bounded_path() -> None:
    cypher = "MATCH (a)-[*1..3]->(b) RETURN a.name AS name LIMIT 50"
    assert validate_cypher(cypher) is True


def test_synthesis_strips_fake_citations() -> None:
    valid = {"doc_462e8ea7adf4", "doc_45bfaf3307fb"}
    text = (
        "Обратный осмос эффективен [doc:doc_462e8ea7adf4]. "
        "Также см. [doc:fake_doc_999]."
    )
    cleaned = strip_invalid_citations(text, valid)
    assert "[doc:doc_462e8ea7adf4]" in cleaned
    assert "fake_doc_999" not in cleaned


def _load_fixture_context() -> RetrievedContext:
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


def test_build_synthesis_context_includes_contradictions() -> None:
    ctx = _load_fixture_context()
    user = build_synthesis_context("тестовый вопрос", ctx)
    assert "[ЗАФИКСИРОВАННЫЕ ПРОТИВОРЕЧИЯ]" in user
    assert "doc_462e8ea7adf4 vs doc_45bfaf3307fb" in user
    facts_idx = user.index("[ФАКТЫ ГРАФА]")
    contradictions_idx = user.index("[ЗАФИКСИРОВАННЫЕ ПРОТИВОРЕЧИЯ]")
    chunks_idx = user.index("[ФРАГМЕНТЫ ДОКУМЕНТОВ]")
    assert facts_idx < contradictions_idx < chunks_idx


def test_find_gaps_linked_pair() -> None:
    """Пара с общим Experiment — пробел не репортится."""
    mock_session = MagicMock()
    mock_session.run.return_value.single.return_value = None

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.synthesis.gaps.get_driver", return_value=mock_driver):
        gaps = find_gaps(["обратный_осмос", "ионный_обмен"])
    assert gaps == []


def test_find_gaps_unlinked_pair() -> None:
    """Пара без Experiment — пробел репортится."""
    mock_record = {"name_a": "обратный осмос", "name_b": "ионный обмен"}
    mock_session = MagicMock()
    mock_session.run.return_value.single.return_value = mock_record

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.synthesis.gaps.get_driver", return_value=mock_driver):
        gaps = find_gaps(["обратный_осмос", "ионный_обмен"])
    assert len(gaps) == 1
    assert "обратный осмос" in gaps[0].description
    assert "ионный обмен" in gaps[0].description


def test_execute_uses_read_session() -> None:
    """Cypher исполняется только через READ-сессию."""
    from app.retrieval.text2cypher import CypherPlan, execute

    mock_session = MagicMock()
    mock_session.run.return_value = iter([{"name": "test"}])
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.retrieval.text2cypher.get_driver", return_value=mock_driver):
        rows = asyncio.run(
            execute(CypherPlan(cypher="MATCH (n) RETURN n.name AS name LIMIT 50", explanation="test"))
        )

    assert len(rows) == 1
    mock_driver.session.assert_called_once_with(default_access_mode=READ_ACCESS)


def test_query_synthesis_fallback_dead_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEATURE_SYNTHESIS=true + мёртвый LLM → extractive ответ < 35 сек."""
    vector_rows = [
        {
            "chunk_id": "chunk-001",
            "text": "Методы обессоливания воды включают обратный осмос.",
            "score": 0.91,
            "doc_id": "doc-001",
            "title": "Методы обессоливания воды",
            "page": 3,
            "year": 2024,
            "geography": "RU",
        }
    ]

    async def fail_synthesize(query: str, ctx: RetrievedContext) -> str:
        raise RuntimeError("LLM недоступен")

    monkeypatch.setattr(query_api.settings, "feature_graph", False)
    monkeypatch.setattr(query_api.settings, "feature_synthesis", True)
    monkeypatch.setattr(
        query_api.vector_search,
        "search",
        lambda *args, **kwargs: vector_rows,
    )
    monkeypatch.setattr(query_api, "synthesize", fail_synthesize)

    started = time.perf_counter()
    response = client.post("/api/query", json={"query": "обессоливание"})
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 35
    result = QueryResponse.model_validate(response.json())
    assert "обратный осмос" in result.answer_markdown or "Найдено" in result.answer_markdown
    assert result.warning is not None
    assert result.meta.mode == "vector"
