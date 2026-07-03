"""Реалистичные мок-данные для демо (обессоливание / сульфаты)."""

from app.schemas.api import (
    Citation,
    Contradiction,
    GraphSubset,
    KnowledgeGap,
    QueryResponse,
    RecommendedExpert,
    SubgraphResponse,
)
from app.schemas.ontology import EntityType, GraphEdge, GraphNode, RelationType

MOCK_GRAPH_NODES: list[GraphNode] = [
    GraphNode(
        id="proc-ro",
        label="Process",
        type=EntityType.PROCESS,
        name="обратный осмос",
        properties={"category": "мембранный метод"},
    ),
    GraphNode(
        id="proc-ie",
        label="Process",
        type=EntityType.PROCESS,
        name="ионный обмен",
        properties={"category": "реагентный метод"},
    ),
    GraphNode(
        id="mat-water",
        label="Material",
        type=EntityType.MATERIAL,
        name="техническая вода",
        properties={},
    ),
    GraphNode(
        id="prop-sulfate",
        label="Property",
        type=EntityType.PROPERTY,
        name="сульфаты",
        properties={"unit": "мг/л"},
    ),
    GraphNode(
        id="prop-tds",
        label="Property",
        type=EntityType.PROPERTY,
        name="сухой остаток",
        properties={"unit": "мг/дм³"},
    ),
    GraphNode(
        id="exp-001",
        label="Experiment",
        type=EntityType.EXPERIMENT,
        name="Пилот обратного осмоса при 250 мг/л SO4",
        properties={"scale": "pilot", "year": 2019},
    ),
    GraphNode(
        id="exp-002",
        label="Experiment",
        type=EntityType.EXPERIMENT,
        name="Ионообменная колонна, сульфаты 280 мг/л",
        properties={"scale": "lab", "year": 2021},
    ),
    GraphNode(
        id="pub-001",
        label="Publication",
        type=EntityType.PUBLICATION,
        name="Обессоливание шахтных вод на Заполярном филиале",
        properties={
            "year": 2019,
            "lang": "ru",
            "doc_type": "report",
            "venue": "Отчёт НИЦ водоподготовки",
            "source_path": "data/corpus/pub-001.pdf",
            "geography": "RU",
        },
    ),
    GraphNode(
        id="pub-002",
        label="Publication",
        type=EntityType.PUBLICATION,
        name="Comparative study of desalination methods for mine water",
        properties={
            "year": 2020,
            "lang": "en",
            "doc_type": "article",
            "venue": "Mine Water and the Environment",
            "source_path": "data/corpus/pub-002.pdf",
            "geography": "WORLD",
        },
    ),
    GraphNode(
        id="expert-ivanov",
        label="Expert",
        type=EntityType.EXPERT,
        name="Иванов А.С.",
        properties={"affiliation": "НИЦ водоподготовки"},
    ),
    GraphNode(
        id="org-zf",
        label="Organization",
        type=EntityType.ORGANIZATION,
        name="ЗФ Норникель",
        properties={"org_type": "company", "country": "RU"},
    ),
    GraphNode(
        id="fac-pilot",
        label="Facility",
        type=EntityType.FACILITY,
        name="Пилотная установка ЗФ",
        properties={"location": "RU"},
    ),
]

MOCK_GRAPH_EDGES: list[GraphEdge] = [
    GraphEdge(
        id="e1",
        source="exp-001",
        target="proc-ro",
        type=RelationType.VALIDATED_BY,
        properties={"confidence": 0.92},
    ),
    GraphEdge(
        id="e2",
        source="exp-001",
        target="prop-sulfate",
        type=RelationType.OPERATES_AT_CONDITION,
        properties={"parameter": "сульфаты", "operator": "<=", "value": 300, "unit": "мг/л"},
    ),
    GraphEdge(
        id="e3",
        source="exp-001",
        target="prop-tds",
        type=RelationType.OPERATES_AT_CONDITION,
        properties={"parameter": "сухой остаток", "operator": "<=", "value": 1000, "unit": "мг/дм³"},
    ),
    GraphEdge(
        id="e4",
        source="exp-001",
        target="pub-001",
        type=RelationType.DESCRIBED_IN,
        properties={},
    ),
    GraphEdge(
        id="e5",
        source="exp-002",
        target="proc-ie",
        type=RelationType.VALIDATED_BY,
        properties={"confidence": 0.88},
    ),
    GraphEdge(
        id="e6",
        source="pub-001",
        target="pub-002",
        type=RelationType.CONTRADICTS,
        properties={"description": "Разные рекомендуемые пределы сульфатов"},
    ),
    GraphEdge(
        id="e7",
        source="pub-001",
        target="expert-ivanov",
        type=RelationType.AUTHORED_BY,
        properties={},
    ),
    GraphEdge(
        id="e8",
        source="exp-001",
        target="fac-pilot",
        type=RelationType.CONDUCTED_AT,
        properties={},
    ),
    GraphEdge(
        id="e9",
        source="exp-001",
        target="mat-water",
        type=RelationType.USES_MATERIAL,
        properties={},
    ),
    GraphEdge(
        id="e10",
        source="expert-ivanov",
        target="org-zf",
        type=RelationType.AFFILIATED_WITH,
        properties={},
    ),
    GraphEdge(
        id="e11",
        source="org-zf",
        target="fac-pilot",
        type=RelationType.OWNS,
        properties={"date_from": "2015"},
    ),
    GraphEdge(
        id="e12",
        source="org-zf",
        target="fac-pilot",
        type=RelationType.OPERATES,
        properties={"date_from": "2016"},
    ),
]

MOCK_QUERY_RESPONSE = QueryResponse(
    answer_markdown="""## Методы обессоливания при сульфатах 200–300 мг/л

### Консенсус
При содержании сульфатов **200–300 мг/л** и сухом остатке **≤ 1000 мг/дм³** в корпусе
преобладают два подхода:

1. **Обратный осмос** — пилотные испытания при 250 мг/л SO₄²⁻ показали стабильное
   снижение минерализации [pub-001] (confidence: 0.92).
2. **Ионный обмен** — лабораторные эксперименты при 280 мг/л [pub-002] (confidence: 0.88).

### Условия экспериментов
| Метод | Сульфаты | Сухой остаток | Масштаб |
|-------|----------|---------------|---------|
| Обратный осмос | ≤ 300 мг/л | ≤ 1000 мг/дм³ | pilot |
| Ионный обмен | 280 мг/л | — | lab |

### Выводы
Для промышленного внедрения при заданных диапазонах рекомендуется приоритизировать
мембранные схемы с пилотной валидацией на площадке ЗФ [pub-001].
""",
    citations=[
        Citation(
            doc_id="pub-001",
            title="Обессоливание шахтных вод на Заполярном филиале",
            snippet="Обратный осмос при 250 мг/л сульфатов обеспечил снижение TDS до 450 мг/дм³.",
            confidence=0.92,
            year=2019,
            geography="RU",
        ),
        Citation(
            doc_id="pub-002",
            title="Comparative study of desalination methods for mine water",
            snippet="Ion exchange effective at sulfate concentrations up to 300 mg/L in bench-scale tests.",
            confidence=0.88,
            year=2020,
            geography="WORLD",
        ),
    ],
    graph_subset=GraphSubset(nodes=MOCK_GRAPH_NODES, edges=MOCK_GRAPH_EDGES),
    contradictions=[
        Contradiction(
            claim_a="Обратный осмос эффективен при сульфатах до 300 мг/л [pub-001]",
            claim_b="Ионный обмен предпочтительнее при сульфатах > 200 мг/л [pub-002]",
            source_a="pub-001",
            source_b="pub-002",
            description="Источники расходятся в рекомендуемом методе при перекрывающихся диапазонах сульфатов.",
        ),
    ],
    knowledge_gaps=[
        KnowledgeGap(
            entities=["обратный осмос", "сульфаты 200-300 мг/л", "промышленный масштаб"],
            missing_link="Experiment",
            description="Нет промышленных экспериментов (industrial scale) при сульфатах 200–300 мг/л и TDS ≤ 1000 мг/дм³.",
        ),
        KnowledgeGap(
            entities=["ионный обмен", "сухой остаток ≤ 1000 мг/дм³"],
            missing_link="Experiment",
            description="Отсутствуют эксперименты ионного обмена с одновременным контролем сухого остатка.",
        ),
    ],
    recommended_experts=[
        RecommendedExpert(
            name="Иванов А.С.",
            affiliation="НИЦ водоподготовки",
            publication_count=3,
            top_publications=["pub-001"],
        ),
        RecommendedExpert(
            name="Smith J.",
            affiliation="Mining Water Research Group",
            publication_count=2,
            top_publications=["pub-002"],
        ),
    ],
    mock=True,
    warning="Ответ на мок-данных. Pipeline retrieval/synthesis ещё не подключён.",
)


def get_mock_query_response() -> QueryResponse:
    """Вернуть копию мок-ответа для API."""
    return MOCK_QUERY_RESPONSE.model_copy(deep=True)


def get_mock_subgraph(node_ids: list[str] | None = None) -> SubgraphResponse:
    """Вернуть subgraph, опционально отфильтрованный по node_ids."""
    nodes = MOCK_GRAPH_NODES
    if node_ids:
        id_set = set(node_ids)
        nodes = [n for n in nodes if n.id in id_set]
        node_id_set = {n.id for n in nodes}
        edges = [
            e
            for e in MOCK_GRAPH_EDGES
            if e.source in node_id_set and e.target in node_id_set
        ]
    else:
        edges = MOCK_GRAPH_EDGES
    return SubgraphResponse(nodes=nodes, edges=edges, mock=True)
