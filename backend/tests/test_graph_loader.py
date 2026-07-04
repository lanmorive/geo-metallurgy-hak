"""Tests for graph loader (unit + optional Neo4j integration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.graph.init_db import split_cypher_statements
from app.graph.loader import (
    _aggregate_entities,
    _build_tmp_id_map,
    load_document,
    read_extraction_records,
)
from app.retrieval.embedder import _text_hash

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
    grouped = _aggregate_entities(records)
    assert len(grouped) == 2
    tmp_map = _build_tmp_id_map(records)
    assert tmp_map["e1"] == ("Material", "штейн мдп")


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

    result1 = emb.load_or_compute_embeddings("doc_test", [chunk])
    assert len(result1["doc_test_00001"]) == 1024

    # second call should hit cache
    call_count = {"n": 0}
    original = emb.embed_texts

    def counting_embed(texts: list[str]) -> list[list[float]]:
        call_count["n"] += 1
        return original(texts)

    monkeypatch.setattr(emb, "embed_texts", counting_embed)
    result2 = emb.load_or_compute_embeddings("doc_test", [chunk])
    assert call_count["n"] == 0
    np.testing.assert_allclose(result2["doc_test_00001"], result1["doc_test_00001"], rtol=1e-5)

    manifest = json.loads((tmp_path / "doc_test.manifest.json").read_text())
    assert manifest["chunk_ids"] == ["doc_test_00001"]
    arr = np.load(tmp_path / "doc_test.npy")
    assert arr.shape == (1, 1024)
