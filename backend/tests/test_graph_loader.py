"""Tests for graph loader (unit + optional Neo4j integration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.graph.init_db import split_cypher_statements
from app.graph.loader import (
    _aggregate_entities,
    _build_tmp_id_map,
    _should_load_entity,
    load_document,
    read_extraction_records,
)
from app.graph.quality import find_duplicate_pairs
from app.graph.stop_entities import is_suspicious_name_norm
from app.retrieval.embedder import _text_hash
from app.schemas.ontology import ChunkExtractionRecord, EntityType, ExtractionResult, ExtractedEntity

FIXTURE = Path(__file__).parent / "fixtures" / "sample_matte.jsonl"


def test_split_cypher_statements_handles_braces() -> None:
    text = """
CREATE CONSTRAINT a IF NOT EXISTS FOR (n:A) REQUIRE (n.x) IS UNIQUE;
CREATE VECTOR INDEX b IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1024,
  `vector.similarity_function`: 'cosine'
}};
"""
    stmts = split_cypher_statements(text)
    assert len(stmts) == 2
    assert "CREATE CONSTRAINT a" in stmts[0]
    assert "chunk_embedding" in stmts[1] or "CREATE VECTOR INDEX b" in stmts[1]


def test_read_fixture_matte() -> None:
    records = read_extraction_records(FIXTURE)
    assert len(records) == 1
    rel = records[0].result.relations[0]
    assert rel.numeric is not None
    assert rel.numeric.value == 31.2
    assert rel.numeric.unit == "% масс."


def test_aggregate_entities_dedup() -> None:
    records = read_extraction_records(FIXTURE)
    stop_set = frozenset()
    grouped = _aggregate_entities(records, stop_set, min_conf=0.5)
    assert len(grouped) == 2
    tmp_map = _build_tmp_id_map(records, stop_set, min_conf=0.5)
    assert tmp_map["e1"] == ("Material", "штейн мдп")


def test_should_load_entity_stop_and_low_confidence() -> None:
    stop_set = frozenset({"процесс"})
    stop_ent = ExtractedEntity(
        tmp_id="x",
        type=EntityType.PROCESS,
        name="Процесс",
        name_norm="процесс",
        confidence=0.9,
    )
    low_conf_material = ExtractedEntity(
        tmp_id="y",
        type=EntityType.MATERIAL,
        name="X",
        name_norm="материал x",
        confidence=0.3,
    )
    low_conf_expert = ExtractedEntity(
        tmp_id="z",
        type=EntityType.EXPERT,
        name="Expert",
        name_norm="эксперт",
        confidence=0.3,
    )
    assert not _should_load_entity(stop_ent, stop_set, 0.5)
    assert not _should_load_entity(low_conf_material, stop_set, 0.5)
    assert _should_load_entity(low_conf_expert, stop_set, 0.5)


def test_aggregate_entities_filters_stop_and_low_confidence() -> None:
    record = ChunkExtractionRecord(
        chunk_id="c1",
        doc_id="doc_test",
        source_doc="doc_test",
        source_chunk="c1",
        result=ExtractionResult(
            entities=[
                ExtractedEntity(
                    tmp_id="e1",
                    type=EntityType.PROCESS,
                    name="Процесс",
                    name_norm="процесс",
                    confidence=0.9,
                ),
                ExtractedEntity(
                    tmp_id="e2",
                    type=EntityType.MATERIAL,
                    name="Low",
                    name_norm="низкая уверенность",
                    confidence=0.2,
                ),
                ExtractedEntity(
                    tmp_id="e3",
                    type=EntityType.MATERIAL,
                    name="Ok",
                    name_norm="нормальный материал",
                    confidence=0.8,
                ),
            ],
            relations=[],
        ),
        model="test",
    )
    stop_set = frozenset({"процесс"})
    grouped = _aggregate_entities([record], stop_set, min_conf=0.5)
    assert len(grouped) == 1
    assert ("Material", "нормальный материал") in grouped


def test_is_suspicious_name_norm() -> None:
    assert is_suspicious_name_norm("ab")
    assert is_suspicious_name_norm("12345")
    assert is_suspicious_name_norm("abc")
    assert not is_suspicious_name_norm("штейн мдп")
    assert not is_suspicious_name_norm("nickel ore")


def test_find_duplicate_pairs() -> None:
    names = {
        "Material": [
            "никель руда",
            "руда никель",
            "медь концентрат",
            "совсем другое",
        ],
    }
    pairs = find_duplicate_pairs(names, limit=10)
    assert pairs
    assert pairs[0].label == "Material"
    assert pairs[0].score > 90


def test_read_slim_extracted_format(tmp_path: Path) -> None:
    path = tmp_path / "doc_test.jsonl"
    path.write_text(
        '{"chunk_id": "doc_test_00001", "doc_id": "doc_test", "retries": 0, '
        '"usage": {"prompt_tokens": 10, "completion_tokens": 5}, '
        '"result": {"entities": [], "relations": []}}\n',
        encoding="utf-8",
    )
    records = read_extraction_records(path)
    assert len(records) == 1
    assert records[0].source_doc == "doc_test"
    assert records[0].source_chunk == "doc_test_00001"
    assert records[0].model == "unknown"


def test_read_skips_null_result(tmp_path: Path) -> None:
    path = tmp_path / "doc_test.jsonl"
    path.write_text(
        '{"chunk_id": "c1", "doc_id": "doc_test", "result": null}\n',
        encoding="utf-8",
    )
    assert read_extraction_records(path) == []


def test_text_hash_stable() -> None:
    h1 = _text_hash("hello")
    h2 = _text_hash("hello")
    assert h1 == h2
    assert h1 != _text_hash("world")


def _neo4j_available() -> bool:
    try:
        from app.graph.driver import close_driver, get_driver

        driver = get_driver()
        driver.verify_connectivity()
        close_driver()
        return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
def test_loader_idempotent_and_has_property_edge() -> None:
    from app.graph.driver import close_driver, get_driver
    from app.graph.init_db import apply_schema

    apply_schema()

    driver = get_driver()
    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (p:Publication {doc_id: $doc_id})
                SET p.title = $title
                """,
                doc_id="sample_matte",
                title="calibration_matte",
            ).consume()

        load_document(FIXTURE, driver)
        with driver.session() as session:
            n1 = session.run(
                "MATCH (n) WHERE n:Material OR n:Property OR n:Process RETURN count(n) AS c"
            ).single()["c"]
            r1 = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            edge = session.run(
                """
                MATCH ()-[r:has_property]->()
                WHERE r.value = 31.2 AND r.unit = '% масс.'
                RETURN count(r) AS c
                """
            ).single()["c"]

        assert edge >= 1

        load_document(FIXTURE, driver)
        with driver.session() as session:
            n2 = session.run(
                "MATCH (n) WHERE n:Material OR n:Property OR n:Process RETURN count(n) AS c"
            ).single()["c"]
            r2 = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

        assert n2 == n1
        assert r2 == r1
    finally:
        close_driver()


def test_embedder_cache_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np

    from app.retrieval import embedder as emb
    from app.schemas.ontology import ParsedChunk

    monkeypatch.setattr(emb, "EMBEDDINGS_DIR", tmp_path)

    chunk = ParsedChunk(
        doc_id="doc_test",
        chunk_id="doc_test_00001",
        text="тестовый текст",
        kind="text",
        section="s",
        lang="ru",
        file_name="f.pdf",
        source_key="raw/f.pdf",
    )

    fake_vec = [0.1] * 1024
    monkeypatch.setattr(emb, "embed_texts", lambda texts: [fake_vec for _ in texts])

    result1_vectors, _, _ = emb.load_or_compute_embeddings("doc_test", [chunk])
    assert len(result1_vectors["doc_test_00001"]) == 1024

    # second call should hit cache
    call_count = {"n": 0}
    original = emb.embed_texts

    def counting_embed(texts: list[str]) -> list[list[float]]:
        call_count["n"] += 1
        return original(texts)

    monkeypatch.setattr(emb, "embed_texts", counting_embed)
    result2_vectors, computed, cached = emb.load_or_compute_embeddings("doc_test", [chunk])
    assert call_count["n"] == 0
    assert computed == 0
    assert cached == 1
    np.testing.assert_allclose(result2_vectors["doc_test_00001"], result1_vectors["doc_test_00001"], rtol=1e-5)

    manifest = json.loads((tmp_path / "doc_test.manifest.json").read_text())
    assert manifest["chunk_ids"] == ["doc_test_00001"]
    arr = np.load(tmp_path / "doc_test.npy")
    assert arr.shape == (1, 1024)
