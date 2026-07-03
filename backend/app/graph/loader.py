"""Загрузка JSONL в Neo4j батчами через UNWIND."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from neo4j import Driver

from app.schemas.ontology import Entity, EntityType, ExtractionResult, Relation

logger = logging.getLogger(__name__)

BATCH_SIZE = 500

_MERGE_BY_NAME_NORM = """
UNWIND $rows AS row
CALL apoc.merge.node([row.type], {name_norm: row.name_norm}, row, row) YIELD node
RETURN count(node) AS cnt
"""

_MERGE_CHUNK_BY_ID = """
UNWIND $rows AS row
CALL apoc.merge.node(['Chunk'], {id: row.id}, row, row) YIELD node
RETURN count(node) AS cnt
"""

_MERGE_RELATION = """
UNWIND $rows AS row
MATCH (src {id: row.source_id})
MATCH (dst {id: row.target_id})
CALL apoc.merge.relationship(
  src,
  row.type,
  {id: row.id},
  row,
  dst
) YIELD rel
RETURN count(rel) AS cnt
"""


def _entity_row(entity: Entity) -> dict[str, Any]:
    """Сериализовать Entity для Neo4j UNWIND."""
    row = entity.model_dump(mode="json")
    row["type"] = entity.type.value
    return row


def _relation_row(relation: Relation) -> dict[str, Any]:
    """Сериализовать Relation для Neo4j UNWIND."""
    row = relation.model_dump(mode="json")
    row["type"] = relation.type.value
    verification = row.pop("verification", {})
    for key, val in verification.items():
        row[f"verification_{key}"] = val
    row["source_doc"] = verification.get("source_doc")
    row["confidence"] = verification.get("confidence")
    row["geography"] = verification.get("geography")
    row["year"] = verification.get("year")
    return row


def load_jsonl(path: Path, driver: Driver) -> tuple[int, int]:
    """
    Загрузить ExtractionResult из JSONL в Neo4j.

    Args:
        path: Путь к data/extracted/*.jsonl
        driver: Neo4j driver.

    Returns:
        Кортеж (число сущностей, число связей).

    Raises:
        NotImplementedError: Полная загрузка — владелец Senior 1.
    """
    logger.info("load_jsonl called for %s", path)
    if not path.exists():
        logger.warning("File not found: %s", path)
        return 0, 0
    raise NotImplementedError(
        "load_jsonl: implement UNWIND batch upsert for entities and relations"
    )


def batch_upsert_entities(driver: Driver, entities: list[Entity]) -> int:
    """
    Батч-вставка/обновление сущностей через UNWIND.

    Chunk мержится по id (нет uniqueness на name_norm); остальные — по name_norm.

    Args:
        driver: Neo4j driver.
        entities: Список сущностей (до BATCH_SIZE).

    Returns:
        Число обработанных записей.
    """
    if not entities:
        return 0

    chunks = [_entity_row(e) for e in entities if e.type == EntityType.CHUNK]
    others = [_entity_row(e) for e in entities if e.type != EntityType.CHUNK]
    total = 0

    with driver.session() as session:
        if others:
            result = session.run(_MERGE_BY_NAME_NORM, rows=others)
            record = result.single()
            total += record["cnt"] if record else 0
        if chunks:
            result = session.run(_MERGE_CHUNK_BY_ID, rows=chunks)
            record = result.single()
            total += record["cnt"] if record else 0

    return total


def batch_upsert_relations(driver: Driver, relations: list[Relation]) -> int:
    """
    Батч-вставка связей через UNWIND.

    Пишет verification, numeric_constraints, date_from/date_to/amount (owns/operates).

    Args:
        driver: Neo4j driver.
        relations: Список связей (до BATCH_SIZE).

    Returns:
        Число обработанных записей.

    Raises:
        NotImplementedError: Реализация merge рёбер — владелец Senior 1.
    """
    logger.info("batch_upsert_relations called, count=%d", len(relations))
    raise NotImplementedError(
        "batch_upsert_relations: implement UNWIND MERGE for typed relationships"
    )


def read_extraction_jsonl(path: Path) -> list[ExtractionResult]:
    """Прочитать JSONL с ExtractionResult."""
    results: list[ExtractionResult] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data: dict[str, Any] = json.loads(line)
            results.append(ExtractionResult.model_validate(data))
    return results


def sync_extracted_from_s3(local_dir: Path) -> int:
    """Скачать extracted/ из S3 в локальную директорию."""
    from app.storage import get_storage

    storage = get_storage()
    if not storage.available:
        return 0
    return storage.sync_prefix_down("extracted/", local_dir)


def _default_extracted_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "extracted"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Sync extracted data from S3")
    parser.add_argument(
        "--from-s3",
        action="store_true",
        help="Download extracted/ prefix from S3 to local directory",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Local extracted directory (default: repo data/extracted)",
    )
    args = parser.parse_args()

    if not args.from_s3:
        parser.error("--from-s3 is required")

    local_dir = args.dir or _default_extracted_dir()
    count = sync_extracted_from_s3(local_dir)
    logger.info("Synced %d files to %s", count, local_dir)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
