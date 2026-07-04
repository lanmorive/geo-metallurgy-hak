"""CLI extraction: data/parsed → data/extracted."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.extraction.extractor import extract_chunk
from app.ingest.manifest import load_manifest, save_manifest
from app.llm import get_llm_client
from app.schemas.ontology import (
    ChunkExtractionRecord,
    ExtractionResult,
    ParsedChunk,
    ParsedDocumentMeta,
)
from app.storage import get_storage

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_PARSED = REPO_ROOT / "data" / "parsed"
DATA_EXTRACTED = REPO_ROOT / "data" / "extracted"
CORE_TERMS_PATH = REPO_ROOT / "data" / "reference" / "core_terms.json"
EXTRACT_MANIFEST_NAME = "_manifest.json"
SAMPLE_OUTPUT = DATA_EXTRACTED / "_sample.jsonl"

# Калибровочный набор: 4 table + 3 frontmatter + 5 text
SAMPLE_CHUNK_IDS = [
    "sample_matte_table",  # synthetic fixture
    "doc_7d11e81f33f5_00041",
    "doc_7d11e81f33f5_00095",
    "doc_7d11e81f33f5_00268",
    "doc_7d11e81f33f5_00011",
    "doc_7d11e81f33f5_00012",
    "doc_7d11e81f33f5_00013",
    "doc_7d11e81f33f5_00052",  # article text (флотация/шины)
    "doc_7d11e81f33f5_00127",  # калий/газ
    "doc_7d11e81f33f5_00155",  # торф/разработка (text)
    "doc_7d11e81f33f5_00629",  # подписка ГП
    "doc_7d11e81f33f5_00098",  # текст статьи (шины/ПДМ)
]

MATTE_TABLE_TEXT = """| Материал | Cu | Ni | Co | Fe | S |
| Штейн МДП | 31,20 | 1,58 | 0,06 | 35,30 | 28,20 |
(шапка: Содержание, % масс.)"""


@dataclass
class DocStats:
    chunks_processed: int = 0
    entities: int = 0
    relations: int = 0
    empty_chunks: int = 0
    failed_chunks: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class RunStats:
    by_doc: dict[str, DocStats] = field(default_factory=dict)
    model: str = ""


def load_core_terms(path: Path = CORE_TERMS_PATH) -> list[str]:
    if not path.exists():
        logger.warning("Core terms file not found: %s", path)
        return []
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    terms = data.get("terms", [])
    return [str(t) for t in terms]


def _chunk_sort_key(chunk: ParsedChunk) -> tuple[int, str]:
    if chunk.kind == "table":
        return (0, chunk.chunk_id)
    if chunk.section == "frontmatter":
        return (1, chunk.chunk_id)
    return (2, chunk.chunk_id)


def read_parsed_chunks(path: Path) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(ParsedChunk.model_validate_json(line))
    chunks.sort(key=_chunk_sort_key)
    return chunks


def load_chunk_by_id(parsed_dir: Path, chunk_id: str) -> ParsedChunk | None:
    if chunk_id == "sample_matte_table":
        return ParsedChunk(
            doc_id="sample_matte",
            chunk_id="sample_matte_table",
            text=MATTE_TABLE_TEXT,
            kind="table",
            section="Характеристика исходных материалов",
            lang="ru",
            file_name="calibration_matte.pdf",
            source_key="calibration/matte.pdf",
            year=2024,
            doc_type="report",
        )
    doc_id = "_".join(chunk_id.split("_")[:2])
    path = parsed_dir / f"{doc_id}.jsonl"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        for line in f:
            chunk = ParsedChunk.model_validate_json(line.strip())
            if chunk.chunk_id == chunk_id:
                return chunk
    return None


def build_sample_chunks(parsed_dir: Path) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []
    for cid in SAMPLE_CHUNK_IDS:
        chunk = load_chunk_by_id(parsed_dir, cid)
        if chunk is None:
            logger.warning("Sample chunk not found: %s", cid)
        else:
            chunks.append(chunk)
    return chunks


def read_meta(parsed_dir: Path, doc_id: str) -> ParsedDocumentMeta | None:
    meta_path = parsed_dir / f"{doc_id}.meta.json"
    if not meta_path.exists():
        return None
    return ParsedDocumentMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))


def doc_matches_core(
    meta: ParsedDocumentMeta,
    chunks: list[ParsedChunk],
    terms: list[str],
) -> bool:
    if not terms:
        return True
    haystack = " ".join(
        [
            meta.file_name or "",
            meta.venue or "",
            *(c.text[:500] for c in chunks[:20]),
        ]
    ).lower()
    return any(term.lower() in haystack for term in terms)


def load_done_chunk_ids(extracted_path: Path) -> set[str]:
    if not extracted_path.exists():
        return set()
    done: set[str] = set()
    with extracted_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = ChunkExtractionRecord.model_validate_json(line)
            done.add(record.chunk_id)
    return done


def read_existing_records(extracted_path: Path) -> list[ChunkExtractionRecord]:
    if not extracted_path.exists():
        return []
    records: list[ChunkExtractionRecord] = []
    with extracted_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(ChunkExtractionRecord.model_validate_json(line))
    return records


def write_records_atomic(path: Path, records: list[ChunkExtractionRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(record.model_dump_json() + "\n")
    tmp.replace(path)


def _estimate_cost_usd(prompt_tokens: int, completion_tokens: int, model: str) -> float | None:
    # gpt-4o-mini pricing approximation
    if "mini" in model.lower():
        return prompt_tokens * 0.15 / 1_000_000 + completion_tokens * 0.60 / 1_000_000
    return None


def make_record(
    chunk: ParsedChunk,
    result: ExtractionResult,
    *,
    model: str,
    retries: int,
    usage: dict[str, Any],
) -> ChunkExtractionRecord:
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    cost = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost = _estimate_cost_usd(prompt_tokens, completion_tokens, model)
    return ChunkExtractionRecord(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        source_doc=chunk.doc_id,
        source_chunk=chunk.chunk_id,
        year=chunk.year,
        result=result,
        model=model,
        retries=retries,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
    )


async def _process_chunks(
    chunks: list[ParsedChunk],
    canonical_terms: list[str],
    *,
    force: bool,
    done_ids: set[str],
    model: str,
    semaphore: asyncio.Semaphore,
) -> list[tuple[ParsedChunk, ExtractionResult | None, int, dict[str, Any]]]:
    async def _one(chunk: ParsedChunk) -> tuple[ParsedChunk, ExtractionResult | None, int, dict[str, Any]]:
        if not force and chunk.chunk_id in done_ids:
            return chunk, None, 0, {}
        async with semaphore:
            result, retries, usage = await extract_chunk(chunk, canonical_terms, model=model)
            return chunk, result, retries, usage

    return await asyncio.gather(*[_one(c) for c in chunks])


def _update_stats(stats: DocStats, result: ExtractionResult | None, usage: dict[str, Any]) -> None:
    stats.chunks_processed += 1
    if result is None:
        stats.failed_chunks += 1
        return
    if not result.entities and not result.relations:
        stats.empty_chunks += 1
    stats.entities += len(result.entities)
    stats.relations += len(result.relations)
    stats.prompt_tokens += usage.get("prompt_tokens") or 0
    stats.completion_tokens += usage.get("completion_tokens") or 0


def print_sample_results(records: list[ChunkExtractionRecord]) -> None:
    print("\n" + "=" * 72)
    print("EXTRACTION SAMPLE RESULTS")
    print("=" * 72)
    for record in records:
        print(f"\n--- {record.chunk_id} (retries={record.retries}) ---")
        if record.result.entities:
            print("\nEntities:")
            print(f"  {'name':<40} {'type':<14} {'name_norm':<30} conf")
            print("  " + "-" * 90)
            for e in record.result.entities:
                print(
                    f"  {e.name[:38]:<40} {e.type.value:<14} {e.name_norm[:28]:<30} {e.confidence:.2f}"
                )
        else:
            print("\nEntities: (none)")
        if record.result.relations:
            print("\nRelations:")
            for r in record.result.relations:
                num = ""
                if r.numeric:
                    n = r.numeric
                    val = n.value if n.value is not None else f"{n.value_min}-{n.value_max}"
                    num = f" numeric={n.parameter} {n.operator} {val} {n.unit}"
                print(
                    f"  {r.source} --[{r.type.value}]--> {r.target}  conf={r.confidence:.2f}{num}"
                )
        else:
            print("\nRelations: (none)")
    print("\n" + "=" * 72)


async def run_sample(parsed_dir: Path, canonical_terms: list[str], *, write: bool = False) -> int:
    chunks = build_sample_chunks(parsed_dir)
    if len(chunks) != 12:
        logger.error("Expected 12 sample chunks, got %d", len(chunks))
        return 1

    model = settings.llm_model
    semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
    results = await _process_chunks(
        chunks,
        canonical_terms,
        force=True,
        done_ids=set(),
        model=model,
        semaphore=semaphore,
    )

    records: list[ChunkExtractionRecord] = []
    for chunk, result, retries, usage in results:
        if result is None:
            logger.error("Sample chunk failed: %s", chunk.chunk_id)
            return 1
        records.append(make_record(chunk, result, model=model, retries=retries, usage=usage))

    print_sample_results(records)
    if write:
        DATA_EXTRACTED.mkdir(parents=True, exist_ok=True)
        write_records_atomic(SAMPLE_OUTPUT, records)
        logger.info("Wrote %d sample records to %s", len(records), SAMPLE_OUTPUT)
    return 0


async def run_extraction(args: argparse.Namespace) -> int:
    parsed_dir = Path(args.parsed_dir)
    extracted_dir = Path(args.extracted_dir)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    canonical_terms = load_core_terms()
    doc_types = {t.strip() for t in args.doc_types.split(",") if t.strip()}
    manifest_path = extracted_dir / EXTRACT_MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    storage = get_storage()
    model = settings.llm_model
    run_stats = RunStats(model=model)

    jsonl_files = sorted(parsed_dir.glob("*.jsonl"))
    if not jsonl_files:
        logger.warning("No parsed JSONL in %s", parsed_dir)
        return 0

    semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
    global_limit = args.limit

    for path in jsonl_files:
        doc_id = path.stem
        meta = read_meta(parsed_dir, doc_id)
        if meta is None:
            logger.warning("No meta for %s, skipping", doc_id)
            continue
        if meta.status not in ("ok", "scan_low_value"):
            logger.info("Skip %s: status=%s", doc_id, meta.status)
            continue
        if args.skip_low_yield and meta.low_yield:
            logger.info("Skip %s: low_yield", doc_id)
            continue
        if meta.doc_type and meta.doc_type not in doc_types:
            logger.info("Skip %s: doc_type=%s", doc_id, meta.doc_type)
            continue

        chunks = read_parsed_chunks(path)
        if args.core_only and not doc_matches_core(meta, chunks, canonical_terms):
            logger.info("Skip %s: no core terms match", doc_id)
            continue

        out_path = extracted_dir / f"{doc_id}.jsonl"
        done_ids = set() if args.force else load_done_chunk_ids(out_path)
        existing = [] if args.force else read_existing_records(out_path)

        pending = [c for c in chunks if args.force or c.chunk_id not in done_ids]
        if global_limit is not None:
            already = len(existing)
            pending = pending[: max(0, global_limit - already)]
        if not pending:
            logger.info("All chunks done for %s", doc_id)
            continue

        logger.info("Extracting %d chunks from %s", len(pending), doc_id)
        doc_stats = DocStats()
        results = await _process_chunks(
            pending,
            canonical_terms,
            force=args.force,
            done_ids=done_ids,
            model=model,
            semaphore=semaphore,
        )

        new_records: list[ChunkExtractionRecord] = []
        for chunk, result, retries, usage in results:
            if result is None:
                _update_stats(doc_stats, None, usage)
                continue
            if chunk.chunk_id in done_ids and not args.force:
                continue
            record = make_record(chunk, result, model=model, retries=retries, usage=usage)
            new_records.append(record)
            _update_stats(doc_stats, result, usage)

        if args.force:
            all_records = new_records
        else:
            existing_map = {r.chunk_id: r for r in existing}
            for r in new_records:
                existing_map[r.chunk_id] = r
            all_records = sorted(existing_map.values(), key=lambda r: r.chunk_id)

        if new_records or args.force:
            write_records_atomic(out_path, all_records)

        if storage.available and out_path.exists():
            storage.upload_file(out_path, f"extracted/{doc_id}.jsonl")

        run_stats.by_doc[doc_id] = doc_stats
        cost = _estimate_cost_usd(doc_stats.prompt_tokens, doc_stats.completion_tokens, model)
        manifest[doc_id] = {
            "status": "ok" if doc_stats.failed_chunks == 0 else "partial",
            "chunks_processed": doc_stats.chunks_processed,
            "entities": doc_stats.entities,
            "relations": doc_stats.relations,
            "empty_chunks": doc_stats.empty_chunks,
            "failed_chunks": doc_stats.failed_chunks,
            "model": model,
            "prompt_tokens": doc_stats.prompt_tokens,
            "completion_tokens": doc_stats.completion_tokens,
            "cost_usd": cost,
        }
        save_manifest(manifest_path, manifest)

        if global_limit is not None:
            total = sum(s.chunks_processed for s in run_stats.by_doc.values())
            if total >= global_limit:
                break

    _print_summary(run_stats)
    return 0


def _print_summary(stats: RunStats) -> None:
    if not stats.by_doc:
        return
    print("\nExtraction summary:")
    for doc_id, s in stats.by_doc.items():
        print(
            f"  {doc_id}: chunks={s.chunks_processed} entities={s.entities} "
            f"relations={s.relations} empty={s.empty_chunks} failed={s.failed_chunks}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM extraction from ParsedChunk JSONL")
    parser.add_argument("--parsed-dir", type=Path, default=DATA_PARSED)
    parser.add_argument("--extracted-dir", type=Path, default=DATA_EXTRACTED)
    parser.add_argument("--force", action="store_true", help="Re-extract all chunks")
    parser.add_argument("--core-only", action="store_true", help="Only docs matching core terms")
    parser.add_argument(
        "--doc-types",
        default="report,presentation,article",
        help="Comma-separated doc types (default excludes journal_issue)",
    )
    parser.add_argument(
        "--skip-low-yield",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip documents with low_yield=true in meta",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max chunks to process (calibration)")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Calibration mode: exactly 12 chunks, print to stdout",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="With --sample: write results to data/extracted/_sample.jsonl",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not settings.llm_api_key:
        logger.error("LLM_API_KEY is not set")
        return 1

    canonical_terms = load_core_terms()

    try:
        asyncio.run(get_llm_client().ensure_available())
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    if args.sample:
        return asyncio.run(run_sample(args.parsed_dir, canonical_terms, write=args.write))
    return asyncio.run(run_extraction(args))


if __name__ == "__main__":
    sys.exit(main())
