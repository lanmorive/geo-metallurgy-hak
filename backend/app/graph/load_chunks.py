"""Load ParsedChunk JSONL + embeddings into Neo4j (Chunk, Publication)."""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from app.graph.driver import close_driver, get_driver
from app.retrieval.embedder import load_or_compute_embeddings
from app.schemas.ontology import ParsedChunk, ParsedDocumentMeta

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_PARSED = REPO_ROOT / "data" / "parsed"
BATCH_SIZE = 500

_MERGE_PUBLICATION = """
MERGE (p:Publication {doc_id: $doc_id})
SET p.title = $title,
    p.year = $year,
    p.lang = $lang,
    p.doc_type = $doc_type,
    p.venue = $venue,
    p.source_path = $source_path,
    p.author_hint = $author_hint
"""

_MERGE_CHUNKS = """
UNWIND $rows AS row
MERGE (c:Chunk {chunk_id: row.chunk_id})
SET c.text = row.text,
    c.embedding = row.embedding,
    c.section = row.section,
    c.kind = row.kind,
    c.page = row.page,
    c.lang = row.lang
WITH c, row
MATCH (p:Publication {doc_id: row.doc_id})
MERGE (c)-[:part_of]->(p)
"""

_FETCH_EMBEDDED_IDS = """
MATCH (c:Chunk)
WHERE c.chunk_id IN $ids AND c.embedding IS NOT NULL
RETURN c.chunk_id AS chunk_id
"""


def read_parsed_chunks(path: Path) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(ParsedChunk.model_validate_json(line))
    return chunks


def read_meta(parsed_dir: Path, doc_id: str) -> ParsedDocumentMeta | None:
    meta_path = parsed_dir / f"{doc_id}.meta.json"
    if not meta_path.exists():
        return None
    return ParsedDocumentMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))


def _publication_title(meta: ParsedDocumentMeta) -> str:
    if meta.file_metadata_title:
        return meta.file_metadata_title
    return Path(meta.file_name).stem


def _majority_lang(chunks: list[ParsedChunk]) -> str:
    if not chunks:
        return "ru"
    counts = Counter(c.lang for c in chunks)
    return counts.most_common(1)[0][0]


def _fetch_existing_embedded(session, chunk_ids: list[str]) -> set[str]:
    if not chunk_ids:
        return set()
    result = session.run(_FETCH_EMBEDDED_IDS, ids=chunk_ids)
    return {r["chunk_id"] for r in result}


def load_document(
    doc_id: str,
    parsed_dir: Path,
    *,
    skip_existing: bool = True,
) -> tuple[int, int, int]:
    """
    Embed and load one document.

    Returns (loaded, skipped, total_chunks).
    """
    jsonl_path = parsed_dir / f"{doc_id}.jsonl"
    meta = read_meta(parsed_dir, doc_id)
    if meta is None:
        logger.warning("No meta for %s, skipping", doc_id)
        return 0, 0, 0
    if meta.status not in ("ok", "scan_low_value"):
        logger.info("Skip %s: status=%s", doc_id, meta.status)
        return 0, 0, 0

    chunks = read_parsed_chunks(jsonl_path)
    if not chunks:
        return 0, 0, 0

    embeddings, _, _ = load_or_compute_embeddings(doc_id, chunks)
    driver = get_driver()

    loaded = 0
    skipped = 0
    with driver.session() as session:
        session.run(
            _MERGE_PUBLICATION,
            doc_id=doc_id,
            title=_publication_title(meta),
            year=meta.year,
            lang=_majority_lang(chunks),
            doc_type=meta.doc_type,
            venue=meta.venue,
            source_path=meta.source_key,
            author_hint=meta.author_hint,
        ).consume()

        existing: set[str] = set()
        if skip_existing:
            existing = _fetch_existing_embedded(session, [c.chunk_id for c in chunks])

        rows: list[dict] = []
        for chunk in chunks:
            if skip_existing and chunk.chunk_id in existing:
                skipped += 1
                continue
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": doc_id,
                    "text": chunk.text,
                    "embedding": embeddings[chunk.chunk_id],
                    "section": chunk.section,
                    "kind": chunk.kind,
                    "page": chunk.page,
                    "lang": chunk.lang,
                }
            )

        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            session.run(_MERGE_CHUNKS, rows=batch).consume()
            loaded += len(batch)

    return loaded, skipped, len(chunks)


def expected_chunk_count(parsed_dir: Path) -> int:
    total = 0
    for meta_path in parsed_dir.glob("*.meta.json"):
        meta = ParsedDocumentMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
        if meta.status in ("ok", "scan_low_value"):
            total += meta.chunks
    return total


def _doc_ids(parsed_dir: Path, pattern: str | None) -> list[str]:
    ids = sorted(p.stem for p in parsed_dir.glob("*.jsonl"))
    if pattern:
        ids = [d for d in ids if fnmatch.fnmatch(d, pattern)]
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed and load parsed chunks into Neo4j")
    parser.add_argument("--parsed-dir", type=Path, default=DATA_PARSED)
    parser.add_argument("--docs", default=None, help="Glob pattern for doc_id")
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-embed and overwrite chunks that already have embeddings in Neo4j",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    doc_ids = _doc_ids(args.parsed_dir, args.docs)
    if not doc_ids:
        logger.warning("No documents found in %s", args.parsed_dir)
        return 0

    total_loaded = 0
    total_skipped = 0
    total_chunks = 0

    try:
        for doc_id in doc_ids:
            loaded, skipped, n = load_document(
                doc_id,
                args.parsed_dir,
                skip_existing=not args.no_skip_existing,
            )
            total_loaded += loaded
            total_skipped += skipped
            total_chunks += n
            if n:
                logger.info("%s: loaded=%d skipped=%d total=%d", doc_id, loaded, skipped, n)

        driver = get_driver()
        with driver.session() as session:
            record = session.run("MATCH (c:Chunk) RETURN count(c) AS cnt").single()
            neo4j_count = record["cnt"] if record else 0

        expected = expected_chunk_count(args.parsed_dir)
        print(
            f"\nSummary: loaded={total_loaded} skipped={total_skipped} "
            f"processed={total_chunks} neo4j_chunks={neo4j_count} expected={expected}"
        )
    finally:
        close_driver()

    return 0


if __name__ == "__main__":
    sys.exit(main())
