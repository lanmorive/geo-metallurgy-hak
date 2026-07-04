"""Unit tests for extraction pipeline (no LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.extraction.extractor import (
    coerce_numeric_strings,
    parse_extraction_json,
    postvalidate,
    strip_json_fence,
)
from app.extraction.run_extraction import (
    load_done_chunk_ids,
    read_existing_records,
    write_records_atomic,
)
from app.schemas.ontology import (
    ChunkExtractionRecord,
    EntityType,
    ExtractionResult,
    ExtractedEntity,
    ExtractedRelation,
    NumericConstraint,
    NumericOperator,
    RelationType,
)


def test_strip_json_fence() -> None:
    raw = '```json\n{"entities":[],"relations":[]}\n```'
    assert strip_json_fence(raw) == '{"entities":[],"relations":[]}'


def test_coerce_numeric_strings_comma_float() -> None:
    data = {
        "entities": [],
        "relations": [
            {
                "source": "e1",
                "target": "e2",
                "type": "has_property",
                "numeric": {
                    "parameter": "содержание Cu",
                    "operator": "=",
                    "value": "31,20",
                    "value_min": None,
                    "value_max": None,
                    "unit": "% масс.",
                },
                "attrs": {},
                "confidence": 0.95,
            }
        ],
    }
    coerced = coerce_numeric_strings(data)
    assert coerced["relations"][0]["numeric"]["value"] == 31.20
    assert coerced["relations"][0]["numeric"]["unit"] == "% масс."


def test_parse_extraction_json_matte() -> None:
    raw = json.dumps(
        {
            "entities": [
                {
                    "tmp_id": "e1",
                    "type": "Material",
                    "name": "Штейн МДП",
                    "name_norm": "штейн мдп",
                    "aliases": [],
                    "geography": "UNKNOWN",
                    "confidence": 0.95,
                },
                {
                    "tmp_id": "e2",
                    "type": "Property",
                    "name": "Содержание Cu",
                    "name_norm": "содержание меди",
                    "aliases": [],
                    "geography": "UNKNOWN",
                    "confidence": 0.95,
                },
            ],
            "relations": [
                {
                    "source": "e1",
                    "target": "e2",
                    "type": "has_property",
                    "numeric": {
                        "parameter": "содержание Cu",
                        "operator": "=",
                        "value": "31,20",
                        "unit": "% масс.",
                    },
                    "attrs": {},
                    "confidence": 0.95,
                }
            ],
        }
    )
    result = parse_extraction_json(raw)
    assert result.relations[0].numeric is not None
    assert result.relations[0].numeric.value == 31.20
    assert result.relations[0].numeric.unit == "% масс."


def test_postvalidate_drops_short_name_norm() -> None:
    result = ExtractionResult(
        entities=[
            ExtractedEntity(
                tmp_id="e1",
                type=EntityType.MATERIAL,
                name="x",
                name_norm="a",
                confidence=0.9,
            )
        ],
        relations=[],
    )
    cleaned = postvalidate(result)
    assert cleaned.entities == []


def test_postvalidate_drops_broken_relation(caplog: pytest.LogCaptureFixture) -> None:
    result = ExtractionResult(
        entities=[
            ExtractedEntity(
                tmp_id="e1",
                type=EntityType.MATERIAL,
                name="руда",
                name_norm="руда",
                confidence=0.9,
            )
        ],
        relations=[
            ExtractedRelation(
                source="e1",
                target="e_missing",
                type=RelationType.HAS_PROPERTY,
                confidence=0.9,
            )
        ],
    )
    with caplog.at_level("WARNING"):
        cleaned = postvalidate(result)
    assert cleaned.relations == []
    assert "Dropped broken relation" in caplog.text


def test_postvalidate_strips_numeric_from_owns() -> None:
    nc = NumericConstraint(
        parameter="test",
        operator=NumericOperator.EQ,
        value=1.0,
        unit="%",
    )
    result = ExtractionResult(
        entities=[
            ExtractedEntity(
                tmp_id="e1",
                type=EntityType.ORGANIZATION,
                name="Cunico",
                name_norm="cunico",
                confidence=0.9,
            ),
            ExtractedEntity(
                tmp_id="e2",
                type=EntityType.FACILITY,
                name="FENI",
                name_norm="завод фени",
                confidence=0.9,
            ),
        ],
        relations=[
            ExtractedRelation(
                source="e1",
                target="e2",
                type=RelationType.OWNS,
                numeric=nc,
                confidence=0.9,
            )
        ],
    )
    cleaned = postvalidate(result)
    assert cleaned.relations[0].numeric is None


def test_empty_json_valid() -> None:
    result = parse_extraction_json('{"entities":[],"relations":[]}')
    assert result.entities == []
    assert result.relations == []


def test_idempotency_skip_done_chunks(tmp_path: Path) -> None:
    out = tmp_path / "doc_test.jsonl"
    record = ChunkExtractionRecord(
        chunk_id="doc_test_00001",
        doc_id="doc_test",
        source_doc="doc_test",
        source_chunk="doc_test_00001",
        year=2024,
        result=ExtractionResult(),
        model="gpt-4o-mini",
        retries=0,
    )
    write_records_atomic(out, [record])
    done = load_done_chunk_ids(out)
    assert "doc_test_00001" in done
    existing = read_existing_records(out)
    assert len(existing) == 1

    record2 = ChunkExtractionRecord(
        chunk_id="doc_test_00002",
        doc_id="doc_test",
        source_doc="doc_test",
        source_chunk="doc_test_00002",
        year=2024,
        result=ExtractionResult(),
        model="gpt-4o-mini",
        retries=0,
    )
    write_records_atomic(out, existing + [record2])
    assert len(load_done_chunk_ids(out)) == 2


def test_force_rewrites_file(tmp_path: Path) -> None:
    out = tmp_path / "doc_test.jsonl"
    write_records_atomic(
        out,
        [
            ChunkExtractionRecord(
                chunk_id="doc_test_00001",
                doc_id="doc_test",
                source_doc="doc_test",
                source_chunk="doc_test_00001",
                result=ExtractionResult(),
                model="old",
                retries=0,
            )
        ],
    )
    write_records_atomic(
        out,
        [
            ChunkExtractionRecord(
                chunk_id="doc_test_00001",
                doc_id="doc_test",
                source_doc="doc_test",
                source_chunk="doc_test_00001",
                result=ExtractionResult(
                    entities=[
                        ExtractedEntity(
                            tmp_id="e1",
                            type=EntityType.MATERIAL,
                            name="штейн",
                            name_norm="штейн",
                            confidence=0.95,
                        )
                    ]
                ),
                model="new",
                retries=0,
            )
        ],
    )
    records = read_existing_records(out)
    assert len(records) == 1
    assert records[0].model == "new"
    assert len(records[0].result.entities) == 1
