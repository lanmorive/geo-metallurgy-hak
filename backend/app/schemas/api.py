"""API-контракты между backend и frontend."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.ontology import GraphEdge, GraphNode, NumericOperator


class NumericFilter(BaseModel):
    """Числовой фильтр в запросе пользователя."""

    parameter: str
    operator: NumericOperator
    value: float
    value_max: float | None = None
    unit: str | None = None


class QueryFilters(BaseModel):
    """Фильтры запроса."""

    geo: str | None = Field(default=None, description="RU, WORLD или ISO-код")
    year_range: tuple[int, int] | None = None
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    numeric_filters: list[NumericFilter] = Field(default_factory=list)


class QueryRequest(BaseModel):
    """Запрос к POST /api/query."""

    query: str
    filters: QueryFilters | None = None


class Citation(BaseModel):
    """Цитата на источник в ответе."""

    doc_id: str
    title: str
    snippet: str
    confidence: float = Field(ge=0.0, le=1.0)
    year: int | None = None
    geography: str = "UNKNOWN"


class Contradiction(BaseModel):
    """Противоречие между источниками."""

    claim_a: str
    claim_b: str
    source_a: str
    source_b: str
    description: str


class KnowledgeGap(BaseModel):
    """Пробел в знаниях — комбинация без Experiment-связей."""

    entities: list[str]
    missing_link: str
    description: str


class RecommendedExpert(BaseModel):
    """Рекомендованный эксперт по теме запроса."""

    name: str
    affiliation: str | None = None
    publication_count: int = 0
    top_publications: list[str] = Field(default_factory=list)


class GraphSubset(BaseModel):
    """Подграф для визуализации."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """Ответ POST /api/query."""

    answer_markdown: str
    citations: list[Citation] = Field(default_factory=list)
    graph_subset: GraphSubset = Field(default_factory=GraphSubset)
    contradictions: list[Contradiction] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    recommended_experts: list[RecommendedExpert] = Field(default_factory=list)
    mock: bool = False
    warning: str | None = None


class SubgraphResponse(BaseModel):
    """Ответ GET /api/graph/subgraph."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    mock: bool = False


class RetrievedContext(BaseModel):
    """Контракт retrieval → synthesis."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    cypher_results: list[dict[str, Any]] = Field(default_factory=list)
