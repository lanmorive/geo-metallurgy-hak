"""Загрузка ChunkExtractionRecord JSONL в Neo4j (сущности + связи)."""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neo4j import Driver

from app.config import settings
from app.graph.driver import close_driver, get_driver
from app.graph.stop_entities import load_stop_entities
from app.schemas.ontology import (
    ChunkExtractionRecord,
    EntityType,
    ExtractedEntity,
    ExtractedRelation,
    RelationType,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_EXTRACTED = REPO_ROOT / "data" / "extracted"
BATCH_SIZE = 500

ENTITY_LABELS: dict[EntityType, str] = {
    EntityType.MATERIAL: "Material",
    EntityType.PROCESS: "Process",
    EntityType.EQUIPMENT: "Equipment",
    EntityType.PROPERTY: "Property",
    EntityType.EXPERIMENT: "Experiment",
    EntityType.EXPERT: "Expert",
    EntityType.ORGANIZATION: "Organization",
    EntityType.FACILITY: "Facility",
}

LOW_CONFIDENCE_EXEMPT_TYPES = frozenset({EntityType.EXPERT, EntityType.ORGANIZATION})

VALID_LABELS = frozenset(ENTITY_LABELS.values())
VALID_REL_TYPES = frozenset(r.value for r in RelationType)

NUMERIC_REL_TYPES = {RelationType.HAS_PROPERTY, RelationType.OPERATES_AT_CONDITION}

_ENTITY_CYPHER: dict[str, str] = {
    label: f"""
UNWIND $rows AS row
MERGE (n:{label} {{name_norm: row.name_norm}})
ON CREATE SET
    n.id = randomUUID(),
    n.name = row.name,
    n.aliases = row.aliases,
    n.geography = row.geography,
    n.confidence = row.confidence,
    n.source_doc = row.source_doc,
    n.source_chunk = row.source_chunk
ON MATCH SET
    n.aliases = apoc.coll.toSet(coalesce(n.aliases, []) + row.aliases),
    n.confidence = CASE
        WHEN row.confidence > coalesce(n.confidence, 0) THEN row.confidence
        ELSE n.confidence
    END
RETURN count(n) AS cnt
"""
    for label in ENTITY_LABELS.values()
}

_MERGE_ENTITY_REL = """
UNWIND $rows AS row
CALL apoc.merge.node([row.src_label], {name_norm: row.src_norm}, {}, {}) YIELD node AS src
CALL apoc.merge.node([row.dst_label], {name_norm: row.dst_norm}, {}, {}) YIELD node AS dst
CALL apoc.merge.relationship(src, row.rel_type, {}, row.props, dst) YIELD rel
RETURN count(rel) AS cnt
"""

_MERGE_ENTITY_TO_PUB = """
UNWIND $rows AS row
CALL apoc.merge.node([row.src_label], {name_norm: row.src_norm}, {}, {}) YIELD node AS src
MATCH (dst:Publication {doc_id: row.doc_id})
CALL apoc.merge.relationship(src, row.rel_type, {}, row.props, dst) YIELD rel
RETURN count(rel) AS cnt
"""

_MERGE_PUB_TO_ENTITY = """
UNWIND $rows AS row
MATCH (src:Publication {doc_id: row.doc_id})
CALL apoc.merge.node([row.dst_label], {name_norm: row.dst_norm}, {}, {}) YIELD node AS dst
CALL apoc.merge.relationship(src, row.rel_type, {}, row.props, dst) YIELD rel
RETURN count(rel) AS cnt
"""

_DESCRIBED_IN_CYPHER = """
UNWIND $rows AS row
CALL apoc.merge.node([row.label], {name_norm: row.name_norm}, {}, {}) YIELD node AS n
MATCH (p:Publication {doc_id: row.doc_id})
MERGE (n)-[r:DESCRIBED_IN]->(p)
SET r.source_chunk = row.source_chunk
RETURN count(r) AS cnt
"""

_PUBLICATION_EXISTS_CYPHER = "MATCH (p:Publication {doc_id: $doc_id}) RETURN count(p) AS cnt"


def _neo4j_rel_type(value: str) -> str:
    """Neo4j-конвенция: типы рёбер в UPPERCASE (t2c и synthesis ждут именно их)."""
    return value.upper()


@dataclass
class EntityRow:
    type: EntityType
    name: str
    name_norm: str
    aliases: list[str]
    geography: str
    confidence: float
    source_doc: str
    source_chunk: str
    tmp_ids: list[str] = field(default_factory=list)


@dataclass
class LoadStats:
    entities: int = 0
    relations: int = 0
    skipped_stop_entities: int = 0
    skipped_low_confidence_entities: int = 0
    skipped_low_confidence_relates_to: int = 0

    def __iadd__(self, other: LoadStats) -> LoadStats:
        self.entities += other.entities
        self.relations += other.relations
        self.skipped_stop_entities += other.skipped_stop_entities
        self.skipped_low_confidence_entities += other.skipped_low_confidence_entities
        self.skipped_low_confidence_relates_to += other.skipped_low_confidence_relates_to
        return self


def read_extraction_records(path: Path) -> list[ChunkExtractionRecord]:
    records: list[ChunkExtractionRecord] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            result = data.get("result")
            if not result:
                continue
            data.setdefault("source_doc", data["doc_id"])
            data.setdefault("source_chunk", data["chunk_id"])
            data.setdefault("model", "unknown")
            usage = data.pop("usage", None) or {}
            data.setdefault("prompt_tokens", usage.get("prompt_tokens"))
            data.setdefault("completion_tokens", usage.get("completion_tokens"))
            for extra in ("kind", "section"):
                data.pop(extra, None)
            records.append(ChunkExtractionRecord.model_validate(data))
    return records


def _should_load_entity(
    ent: ExtractedEntity,
    stop_set: frozenset[str],
    min_conf: float,
) -> bool:
    if ent.name_norm.strip().lower() in stop_set:
        return False
    if ent.confidence < min_conf and ent.type not in LOW_CONFIDENCE_EXEMPT_TYPES:
        return False
    return True


def _count_skipped_entities(
    records: list[ChunkExtractionRecord],
    stop_set: frozenset[str],
    min_conf: float,
) -> tuple[int, int]:
    skipped_stop = 0
    skipped_low_conf = 0
    seen: set[tuple[EntityType, str]] = set()
    for record in records:
        for ent in record.result.entities:
            if ent.type not in ENTITY_LABELS:
                continue
            key = (ent.type, ent.name_norm)
            if key in seen:
                continue
            seen.add(key)
            norm = ent.name_norm.strip().lower()
            if norm in stop_set:
                skipped_stop += 1
            elif ent.confidence < min_conf and ent.type not in LOW_CONFIDENCE_EXEMPT_TYPES:
                skipped_low_conf += 1
    return skipped_stop, skipped_low_conf


def _aggregate_entities(
    records: list[ChunkExtractionRecord],
    stop_set: frozenset[str],
    min_conf: float,
) -> dict[tuple[EntityType, str], EntityRow]:
    grouped: dict[tuple[EntityType, str], EntityRow] = {}
    for record in records:
        for ent in record.result.entities:
            if ent.type not in ENTITY_LABELS:
                continue
            if not _should_load_entity(ent, stop_set, min_conf):
                continue
            key = (ent.type, ent.name_norm)
            if key not in grouped:
                grouped[key] = EntityRow(
                    type=ent.type,
                    name=ent.name,
                    name_norm=ent.name_norm,
                    aliases=list(ent.aliases),
                    geography=ent.geography,
                    confidence=ent.confidence,
                    source_doc=record.doc_id,
                    source_chunk=record.chunk_id,
                    tmp_ids=[ent.tmp_id],
                )
            else:
                row = grouped[key]
                row.aliases = list(set(row.aliases + ent.aliases))
                if ent.confidence > row.confidence:
                    row.confidence = ent.confidence
                if ent.tmp_id not in row.tmp_ids:
                    row.tmp_ids.append(ent.tmp_id)
    return grouped


def _entity_to_dict(row: EntityRow) -> dict[str, Any]:
    return {
        "name": row.name,
        "name_norm": row.name_norm,
        "aliases": row.aliases,
        "geography": row.geography,
        "confidence": row.confidence,
        "source_doc": row.source_doc,
        "source_chunk": row.source_chunk,
    }


def _build_tmp_id_map(
    records: list[ChunkExtractionRecord],
    stop_set: frozenset[str],
    min_conf: float,
) -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    for record in records:
        for ent in record.result.entities:
            if ent.type in ENTITY_LABELS and _should_load_entity(ent, stop_set, min_conf):
                mapping[ent.tmp_id] = (ENTITY_LABELS[ent.type], ent.name_norm)
    return mapping


def _relation_props(
    rel: ExtractedRelation,
    doc_id: str,
    source_chunk: str,
) -> dict[str, Any]:
    props: dict[str, Any] = {
        "source_doc": doc_id,
        "source_chunk": source_chunk,
        "confidence": rel.confidence,
    }
    if rel.type in NUMERIC_REL_TYPES and rel.numeric is not None:
        n = rel.numeric
        props["parameter"] = n.parameter
        props["operator"] = n.operator.value if hasattr(n.operator, "value") else n.operator
        props["value"] = n.value
        props["value_min"] = n.value_min
        props["value_max"] = n.value_max
        props["unit"] = n.unit
    for k, v in rel.attrs.items():
        props[k] = v
    return props


def _resolve_ref(
    ref: str,
    tmp_map: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    if ref == "DOC":
        return None
    if ref not in tmp_map:
        return None
    label, name_norm = tmp_map[ref]
    if label not in VALID_LABELS:
        return None
    return label, name_norm


def phase1_entities(driver: Driver, grouped: dict[tuple[EntityType, str], EntityRow]) -> int:
    by_label: dict[str, list[dict[str, Any]]] = {lbl: [] for lbl in ENTITY_LABELS.values()}
    for row in grouped.values():
        by_label[ENTITY_LABELS[row.type]].append(_entity_to_dict(row))

    total = 0
    with driver.session() as session:
        for label, rows in by_label.items():
            if not rows:
                continue
            cypher = _ENTITY_CYPHER[label]
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                result = session.run(cypher, rows=batch)
                record = result.single()
                total += record["cnt"] if record else 0
    return total


def phase2_relations(
    driver: Driver,
    records: list[ChunkExtractionRecord],
    doc_id: str,
    tmp_map: dict[str, tuple[str, str]],
    stop_set: frozenset[str],
    min_conf: float,
) -> tuple[int, int]:
    entity_rels: list[dict[str, Any]] = []
    entity_to_pub: list[dict[str, Any]] = []
    pub_to_entity: list[dict[str, Any]] = []
    described_in_rows: list[dict[str, Any]] = []
    seen_described: set[tuple[str, str, str]] = set()
    skipped_low_conf_relates_to = 0

    for record in records:
        for ent in record.result.entities:
            if ent.type not in ENTITY_LABELS:
                continue
            if not _should_load_entity(ent, stop_set, min_conf):
                continue
            label = ENTITY_LABELS[ent.type]
            key = (label, ent.name_norm, record.doc_id)
            if key not in seen_described:
                seen_described.add(key)
                described_in_rows.append(
                    {
                        "label": label,
                        "name_norm": ent.name_norm,
                        "doc_id": record.doc_id,
                        "source_chunk": record.chunk_id,
                    }
                )

        for rel in record.result.relations:
            if rel.type.value not in VALID_REL_TYPES:
                logger.warning("Unknown relation type %s", rel.type)
                continue

            if rel.type == RelationType.RELATES_TO and rel.confidence < min_conf:
                skipped_low_conf_relates_to += 1
                continue

            props = _relation_props(rel, doc_id, record.chunk_id)
            src_is_doc = rel.source == "DOC"
            dst_is_doc = rel.target == "DOC"

            if src_is_doc and dst_is_doc:
                logger.warning("Skipping relation with both ends DOC: %s", rel.type.value)
                continue

            if src_is_doc:
                dst = _resolve_ref(rel.target, tmp_map)
                if dst is None:
                    logger.warning(
                        "Skipping broken relation %s: target=%s in %s",
                        rel.type.value,
                        rel.target,
                        record.chunk_id,
                    )
                    continue
                pub_to_entity.append(
                    {
                        "doc_id": doc_id,
                        "dst_label": dst[0],
                        "dst_norm": dst[1],
                        "rel_type": _neo4j_rel_type(rel.type.value),
                        "props": props,
                    }
                )
                continue

            if dst_is_doc:
                src = _resolve_ref(rel.source, tmp_map)
                if src is None:
                    logger.warning(
                        "Skipping broken relation %s: source=%s in %s",
                        rel.type.value,
                        rel.source,
                        record.chunk_id,
                    )
                    continue
                entity_to_pub.append(
                    {
                        "src_label": src[0],
                        "src_norm": src[1],
                        "doc_id": doc_id,
                        "rel_type": _neo4j_rel_type(rel.type.value),
                        "props": props,
                    }
                )
                continue

            src = _resolve_ref(rel.source, tmp_map)
            dst = _resolve_ref(rel.target, tmp_map)
            if src is None or dst is None:
                logger.warning(
                    "Skipping broken relation %s: source=%s target=%s in %s",
                    rel.type.value,
                    rel.source,
                    rel.target,
                    record.chunk_id,
                )
                continue

            entity_rels.append(
                {
                    "src_label": src[0],
                    "src_norm": src[1],
                    "dst_label": dst[0],
                    "dst_norm": dst[1],
                    "rel_type": _neo4j_rel_type(rel.type.value),
                    "props": props,
                }
            )

    total = 0
    with driver.session() as session:
        needs_pub = bool(entity_to_pub or pub_to_entity or described_in_rows)
        if needs_pub:
            pub_record = session.run(_PUBLICATION_EXISTS_CYPHER, doc_id=doc_id).single()
            if not pub_record or pub_record["cnt"] == 0:
                logger.error(
                    "Publication %s not found: %d pub-linked relations will write 0 rows. "
                    "Run load-chunks before load-graph.",
                    doc_id,
                    len(entity_to_pub) + len(pub_to_entity) + len(described_in_rows),
                )

        for name, rows, cypher in (
            ("entity_rels", entity_rels, _MERGE_ENTITY_REL),
            ("entity_to_pub", entity_to_pub, _MERGE_ENTITY_TO_PUB),
            ("pub_to_entity", pub_to_entity, _MERGE_PUB_TO_ENTITY),
        ):
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                result = session.run(cypher, rows=batch)
                record = result.single()
                cnt = record["cnt"] if record else 0
                if batch and cnt == 0:
                    logger.error("phase2 %s batch wrote 0/%d relations in %s", name, len(batch), doc_id)
                total += cnt

        described_in_written = 0
        for i in range(0, len(described_in_rows), BATCH_SIZE):
            batch = described_in_rows[i : i + BATCH_SIZE]
            result = session.run(_DESCRIBED_IN_CYPHER, rows=batch)
            record = result.single()
            cnt = record["cnt"] if record else 0
            described_in_written += cnt
            total += cnt

        if described_in_rows and described_in_written == 0:
            logger.error(
                "phase2 DESCRIBED_IN wrote 0/%d relations in %s (Publication missing?)",
                len(described_in_rows),
                doc_id,
            )

    return total, skipped_low_conf_relates_to


def load_document(
    path: Path,
    driver: Driver,
    stop_set: frozenset[str] | None = None,
    min_conf: float | None = None,
) -> LoadStats:
    records = read_extraction_records(path)
    stats = LoadStats()
    if not records:
        return stats

    if stop_set is None:
        stop_set = load_stop_entities()
    if min_conf is None:
        min_conf = settings.load_min_confidence

    doc_id = records[0].doc_id
    skipped_stop, skipped_low_conf = _count_skipped_entities(records, stop_set, min_conf)
    stats.skipped_stop_entities = skipped_stop
    stats.skipped_low_confidence_entities = skipped_low_conf

    grouped = _aggregate_entities(records, stop_set, min_conf)
    tmp_map = _build_tmp_id_map(records, stop_set, min_conf)

    stats.entities = phase1_entities(driver, grouped)
    n_relations, skipped_rel = phase2_relations(
        driver, records, doc_id, tmp_map, stop_set, min_conf
    )
    stats.relations = n_relations
    stats.skipped_low_confidence_relates_to = skipped_rel

    logger.info(
        "Loaded %s: entities=%d relations=%d skipped_stop=%d skipped_low_conf_entity=%d skipped_low_conf_relates_to=%d",
        path.name,
        stats.entities,
        stats.relations,
        stats.skipped_stop_entities,
        stats.skipped_low_confidence_entities,
        stats.skipped_low_confidence_relates_to,
    )
    return stats


def load_jsonl(path: Path, driver: Driver) -> LoadStats:
    return load_document(path, driver)


def _extracted_files(extracted_dir: Path, pattern: str | None, single_file: Path | None) -> list[Path]:
    if single_file is not None:
        return [single_file]
    files = sorted(extracted_dir.glob("*.jsonl"))
    files = [f for f in files if not f.name.startswith("_")]
    if pattern:
        files = [f for f in files if fnmatch.fnmatch(f.stem, pattern)]
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load extraction JSONL into Neo4j graph")
    parser.add_argument("--extracted-dir", type=Path, default=DATA_EXTRACTED)
    parser.add_argument("--file", type=Path, default=None, help="Single JSONL file to load")
    parser.add_argument("--docs", default=None, help="Glob pattern for doc_id stem")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    file_arg = args.file
    if file_arg is not None and not file_arg.is_absolute():
        file_arg = REPO_ROOT / file_arg

    paths = _extracted_files(args.extracted_dir, args.docs, file_arg)
    if not paths:
        logger.warning("No extraction files found")
        return 0

    stop_set = load_stop_entities()
    min_conf = settings.load_min_confidence

    driver = get_driver()
    total = LoadStats()
    try:
        for path in paths:
            total += load_document(path, driver, stop_set=stop_set, min_conf=min_conf)
        logger.info(
            "Total: entities=%d relations=%d from %d files skipped_stop=%d skipped_low_conf_entity=%d skipped_low_conf_relates_to=%d",
            total.entities,
            total.relations,
            len(paths),
            total.skipped_stop_entities,
            total.skipped_low_confidence_entities,
            total.skipped_low_confidence_relates_to,
        )
    finally:
        close_driver()
    return 0


if __name__ == "__main__":
    sys.exit(main())
