# НЕ МЕНЯТЬ БЕЗ СОГЛАСОВАНИЯ ВСЕЙ КОМАНДЫ
"""
Онтология графа знаний «Научный клубок».

Единственный источник правды для типов сущностей, связей и промежуточных
контрактов pipeline (ParsedChunk, ExtractionResult).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    MATERIAL = "Material"
    PROCESS = "Process"
    EQUIPMENT = "Equipment"
    PROPERTY = "Property"
    EXPERIMENT = "Experiment"
    PUBLICATION = "Publication"
    EXPERT = "Expert"
    FACILITY = "Facility"


class RelationType(StrEnum):
    USES_MATERIAL = "uses_material"
    OPERATES_AT_CONDITION = "operates_at_condition"
    PRODUCES_OUTPUT = "produces_output"
    DESCRIBED_IN = "described_in"
    VALIDATED_BY = "validated_by"
    CONTRADICTS = "contradicts"
    AUTHORED_BY = "authored_by"
    CONDUCTED_AT = "conducted_at"
    USES_EQUIPMENT = "uses_equipment"
    RELATES_TO = "relates_to"


class Geography(StrEnum):
    RU = "RU"
    WORLD = "WORLD"
    UNKNOWN = "UNKNOWN"


class NumericOperator(StrEnum):
    LTE = "<="
    GTE = ">="
    EQ = "="
    RANGE = "range"


class ExperimentScale(StrEnum):
    LAB = "lab"
    PILOT = "pilot"
    INDUSTRIAL = "industrial"


class DocType(StrEnum):
    ARTICLE = "article"
    REPORT = "report"
    PATENT = "patent"
    CATALOG = "catalog"
    OTHER = "other"


class VerificationMeta(BaseModel):
    """Метаданные верификации на каждом узле-факте и ребре."""

    source_doc: str = Field(..., description="Путь или id документа-источника")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность LLM 0..1")
    geography: str = Field(
        default="UNKNOWN",
        description='География: "RU" | "WORLD" | ISO-код | "UNKNOWN"',
    )
    year: int | None = Field(default=None, description="Год публикации/эксперимента")


class NumericConstraint(BaseModel):
    """Числовое ограничение на ребре operates_at_condition или на Property."""

    parameter: str = Field(..., description='Параметр, напр. "сульфаты", "температура"')
    operator: NumericOperator = Field(..., description="<=, >=, =, range")
    value: float = Field(..., description="Числовое значение (value_min для range)")
    value_max: float | None = Field(
        default=None, description="Верхняя граница для operator=range"
    )
    unit: str = Field(..., description='Единица как в источнике, напр. "мг/л"')


class Entity(BaseModel):
    """Узел графа знаний."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EntityType
    name: str
    name_norm: str = ""
    aliases: list[str] = Field(default_factory=list)

    # Type-specific optional attributes
    formula: str | None = None
    class_: str | None = Field(default=None, alias="class")
    category: str | None = None
    model: str | None = None
    vendor: str | None = None
    unit: str | None = None
    title: str | None = None
    date: str | None = None
    scale: ExperimentScale | None = None
    year: int | None = None
    lang: str | None = None
    doc_type: DocType | None = None
    source_path: str | None = None
    affiliation: str | None = None
    location: str | None = None

    verification: VerificationMeta
    embedding: list[float] | None = None

    model_config = {"populate_by_name": True}


class Relation(BaseModel):
    """Ребро графа знаний."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: RelationType
    source_id: str
    target_id: str
    numeric_constraints: list[NumericConstraint] = Field(default_factory=list)
    verification: VerificationMeta


class ChunkMetadata(BaseModel):
    """Метаданные документа для ParsedChunk."""

    title: str | None = None
    year: int | None = None
    geography: str = "UNKNOWN"
    doc_type: DocType = DocType.OTHER


class ParsedChunk(BaseModel):
    """Контракт ingest → extraction: один чанк документа."""

    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str
    source_path: str
    text: str
    page: int | None = None
    lang: str = "ru"
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)


class ExtractionResult(BaseModel):
    """Результат извлечения из одного документа/чанка."""

    doc_id: str
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class GraphNode(BaseModel):
    """Узел для визуализации subgraph."""

    id: str
    label: str
    type: EntityType
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Ребро для визуализации subgraph."""

    id: str
    source: str
    target: str
    type: RelationType
    properties: dict[str, Any] = Field(default_factory=dict)
