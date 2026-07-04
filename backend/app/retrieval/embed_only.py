"""Embed all parsed chunks to data/embeddings/ cache — no Neo4j required."""

from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from pathlib import Path

from app.retrieval.embedder import EMBEDDINGS_DIR, load_or_compute_embeddings
from app.schemas.ontology import ParsedChunk, ParsedDocumentMeta

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_PARSED = REPO_ROOT / "data" / "parsed"


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


def embed_document(
    doc_id: str,
    parsed_dir: Path,
    *,
    force: bool = False,
) -> tuple[int, int, int]:
    """Embed one document to disk cache. Returns (total, computed, cached)."""
    meta = read_meta(parsed_dir, doc_id)
    if meta is None:
        logger.warning("No meta for %s, skipping", doc_id)
        return 0, 0, 0
    if meta.status not in ("ok", "scan_low_value"):
        logger.info("Skip %s: status=%s", doc_id, meta.status)
        return 0, 0, 0

    chunks = read_parsed_chunks(parsed_dir / f"{doc_id}.jsonl")
    if not chunks:
        return 0, 0, 0

    _, computed, cached = load_or_compute_embeddings(doc_id, chunks, force=force)
    return len(chunks), computed, cached


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute chunk embeddings to data/embeddings/ (no Neo4j)"
    )
    parser.add_argument("--parsed-dir", type=Path, default=DATA_PARSED)
    parser.add_argument("--docs", default=None, help="Glob pattern for doc_id")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute all embeddings even if cache is valid",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    doc_ids = _doc_ids(args.parsed_dir, args.docs)
    if not doc_ids:
        logger.warning("No documents found in %s", args.parsed_dir)
        return 0

    total_chunks = 0
    total_computed = 0
    total_cached = 0
    docs_done = 0

    for doc_id in doc_ids:
        n, computed, cached = embed_document(doc_id, args.parsed_dir, force=args.force)
        if n == 0:
            continue
        docs_done += 1
        total_chunks += n
        total_computed += computed
        total_cached += cached
        logger.info("%s: chunks=%d computed=%d cached=%d", doc_id, n, computed, cached)

    cached_files = len(list(EMBEDDINGS_DIR.glob("*.npy"))) if EMBEDDINGS_DIR.exists() else 0
    expected = expected_chunk_count(args.parsed_dir)
    print(
        f"\nSummary: docs={docs_done} chunks={total_chunks} "
        f"computed={total_computed} cached={total_cached} "
        f"cache_files={cached_files} expected_chunks={expected} "
        f"dir={EMBEDDINGS_DIR}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
