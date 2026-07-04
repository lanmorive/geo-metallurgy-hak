"""E2E smoke tests на 4 эталонных запроса из DEMO.md."""

from fastapi.testclient import TestClient
import pytest

from app.api import query as query_api
from app.main import app
from app.schemas.api import QueryResponse

client = TestClient(app)

# TODO: заменить на дословные формулировки с платформы хакатона
REFERENCE_QUERIES = [
  # 1. Числовые диапазоны (обессоливание, сульфаты, сухой остаток)
    "Какие методы обессоливания воды применялись при содержании сульфатов 200–300 мг/л "
    "и сухом остатке ≤ 1000 мг/дм³? Приведи источники и условия.",
    # 2. Эксперименты по процессу с фильтрами гео+год
    "Найди эксперименты по кучному выщелачиванию никелевых руд в России после 2015 года.",
    # 3. Материал → свойства → режимы, противоречия
    "Какие режимы обработки влияют на извлечение меди при флотации? "
    "Где источники противоречат друг другу?",
    # 4. Эксперты
    "Кто в компании / в литературе занимался очисткой сточных вод от сульфатов? "
    "Какие у них публикации?",
]

VECTOR_ROWS = [
    {
        "chunk_id": "chunk-001",
        "text": "Методы обессоливания воды включают обратный осмос и ионный обмен.",
        "score": 0.91,
        "doc_id": "doc-001",
        "title": "Методы обессоливания воды",
        "page": 3,
        "section": "Введение",
        "year": 2024,
        "venue": "Тестовый корпус",
        "doc_type": "report",
        "lang": "ru",
        "geography": "RU",
    }
]


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["neo4j"] in ("ok", "unavailable")


def test_query_reference_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_api.vector_search, "search", lambda *args, **kwargs: VECTOR_ROWS)

    for query_text in REFERENCE_QUERIES:
        response = client.post("/api/query", json={"query": query_text})
        assert response.status_code == 200, f"Failed for: {query_text[:60]}"
        result = QueryResponse.model_validate(response.json())
        assert result.answer_markdown.strip(), "answer_markdown must not be empty"
        assert result.mock is False
        assert result.meta.mode in ("vector", "vector+graph", "full")
        assert result.meta.took_ms >= 0
        assert result.citations, "citations must not be empty"
        assert result.graph_subset.nodes, "graph_subset must have nodes"


def test_subgraph() -> None:
    response = client.get("/api/graph/subgraph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert data["mock"] is False


def test_graph_stats() -> None:
    response = client.get("/api/graph/stats")
    assert response.status_code == 200
    data = response.json()
    assert {"entities", "chunks", "publications", "mock"}.issubset(data)


def test_query_maps_year_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_search(query: str, top_k: int, filters: dict) -> list[dict]:
        captured.update({"query": query, "top_k": top_k, "filters": filters})
        return VECTOR_ROWS

    monkeypatch.setattr(query_api.vector_search, "search", fake_search)
    response = client.post(
        "/api/query",
        json={"query": "обессоливание", "filters": {"year_range": [2024, 2024]}},
    )
    assert response.status_code == 200
    assert captured["top_k"] == 10
    assert captured["filters"] == {"year_min": 2024, "year_max": 2024, "min_confidence": 0.0}


def test_query_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_api.vector_search, "search", lambda *args, **kwargs: [])
    response = client.post("/api/query", json={"query": "нет такого термина"})
    assert response.status_code == 200
    result = QueryResponse.model_validate(response.json())
    assert result.citations == []
    assert "Ничего не найдено" in result.answer_markdown
    assert result.meta.mode == "vector"


def test_query_vector_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_search(*args, **kwargs) -> list[dict]:
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(query_api.vector_search, "search", fail_search)
    response = client.post("/api/query", json={"query": "обессоливание"})
    assert response.status_code == 503
