# НЕ МЕНЯТЬ БЕЗ СОГЛАСОВАНИЯ ВСЕЙ КОМАНДЫ
"""
Онтология графа знаний «Научный клубок».

Единственный источник правды для типов сущностей, связей и промежуточных
контрактов pipeline (ParsedChunk, ExtractionResult).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator


class EntityType(StrEnum):
    MATERIAL = "Material"
    PROCESS = "Process"
    EQUIPMENT = "Equipment"
    PROPERTY = "Property"
    EXPERIMENT = "Experiment"
    PUBLICATION = "Publication"
    CHUNK = "Chunk"
    EXPERT = "Expert"
    ORGANIZATION = "Organization"
    FACILITY = "Facility"


class RelationType(StrEnum):
    USES_MATERIAL = "uses_material"
    OPERATES_AT_CONDITION = "operates_at_condition"
    PRODUCES_OUTPUT = "produces_output"
    DESCRIBED_IN = "described_in"
    VALIDATED_BY = "validated_by"
    CONTRADICTS = "contradicts"
    AUTHORED_BY = "authored_by"
    AFFILIATED_WITH = "affiliated_with"
    OWNS = "owns"
    OPERATES = "operates"
    CONDUCTED_AT = "conducted_at"
    USES_EQUIPMENT = "uses_equipment"
    PART_OF = "part_of"
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
    REPORT = "report"
    ARTICLE = "article"
    PRESENTATION = "presentation"
    REFERENCE = "reference"


class Lang(StrEnum):
    RU = "ru"
    EN = "en"


class OrgType(StrEnum):
    COMPANY = "company"
    INSTITUTE = "institute"
    JV = "JV"


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
    value: float | None = Field(default=None, description="Числовое значение для <=, >=, =")
    value_min: float | None = Field(default=None, description="Нижняя граница для operator=range")
    value_max: float | None = Field(default=None, description="Верхняя граница для operator=range")
    unit: str = Field(..., description='Единица как в источнике, напр. "мг/л"')

    @model_validator(mode="after")
    def validate_numeric_values(self) -> Self:
        if self.operator == NumericOperator.RANGE:
            vmin = self.value_min
            if vmin is None and self.value is not None:
                vmin = self.value
            if vmin is None or self.value_max is None:
                raise ValueError("operator=range requires value_min and value_max")
            return self.model_copy(update={"value_min": vmin, "value": None})
        if self.value is None:
            raise ValueError(f"operator={self.operator} requires value")
        return self


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
    lang: Lang | None = None
    doc_type: DocType | None = None
    venue: str | None = None
    source_path: str | None = None
    org_type: OrgType | None = None
    country: str | None = None
    text: str | None = None
    chunk_index: int | None = None
    affiliation: str | None = None
    location: str | None = None

    verification: VerificationMeta
    embedding: list[float] | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_publication_fields(self) -> Self:
        if self.type == EntityType.PUBLICATION and not self.source_path:
            raise ValueError("Publication requires source_path")
        return self


class Relation(BaseModel):
    """Ребро графа знаний."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: RelationType
    source_id: str
    target_id: str
    numeric_constraints: list[NumericConstraint] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    amount: str | None = None
    verification: VerificationMeta


class ChunkMetadata(BaseModel):
    """Метаданные документа для ParsedChunk."""

    title: str | None = None
    year: int | None = None
    geography: str = "UNKNOWN"
    doc_type: DocType = DocType.REPORT
    lang: Lang = Lang.RU


class ParsedChunk(BaseModel):
    """Контракт ingest → extraction: один чанк документа."""

    doc_id: str
    chunk_id: str
    text: str
    kind: Literal["text", "table"]
    section: str
    page: int | None = None
    lang: Literal["ru", "en"]
    file_name: str
    source_key: str
    author_hint: str | None = None


class ParsedDocumentMeta(BaseModel):
    """Sidecar-метаданные документа после ingest (не в JSONL)."""

    doc_id: str
    file_name: str
    source_key: str
    file_hash: str
    file_metadata_author: str | None = None
    author_hint: str | None = None
    created: str | None = None
    pages: int | None = None
    chunks: int
    tables: int
    ocr_pages: int
    ocr_low_yield_pages: int = 0
    noise_blocks_dropped: int
    text_chars: int = 0
    text_chars_per_page: float | None = None
    low_yield: bool = False
    status: Literal["ok", "error", "skipped_too_large"]
    error: str | None = None
    processing_seconds: float | None = None


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
