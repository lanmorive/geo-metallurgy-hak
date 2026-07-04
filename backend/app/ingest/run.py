"""CLI-оркестратор ingest: S3 → parse → chunk → JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import tempfile
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from app.ingest.authors import extract_author_hint
from app.ingest.chunker import blocks_to_chunks, write_jsonl, write_references
from app.ingest.manifest import MANIFEST_NAME, load_manifest, save_manifest
from app.ingest.parser import parse_file
from app.ingest.pdf_parser import count_pdf_pages
from app.ingest.source_meta import parse_source_key
from app.schemas.ontology import ParsedDocumentMeta
from app.storage import get_storage

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_PARSED = REPO_ROOT / "data" / "parsed"
DEFAULT_CORPUS_PREFIX = "raw/Задача 2. Научный клубок"
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_PDF_PAGES = 500
MANIFEST_FLUSH_EVERY = 10
SUPPORTED_SUFFIXES = {".pdf", ".docx"}


@dataclass
class FileJob:
  source_key: str
  file_name: str
  etag: str
  size: int
  local_path: Path | None = None


@dataclass
class ProcessOutput:
  file_hash: str
  doc_id: str
  source_key: str
  file_name: str
  etag: str
  meta: ParsedDocumentMeta
  processing_seconds: float


def file_sha256(path: Path) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
      h.update(chunk)
  return h.hexdigest()


def doc_id_from_hash(file_hash: str) -> str:
  return f"doc_{file_hash[:12]}"


def _manifest_entry_for_key(manifest: dict, source_key: str) -> dict | None:
  for entry in manifest.values():
    if entry.get("source_key") == source_key and entry.get("status") in (
      "ok",
      "skipped_too_large",
      "scan_low_value",
    ):
      return entry
  return None


def _should_skip_by_key(manifest: dict, source_key: str, etag: str, *, force: bool) -> bool:
  if force:
    return False
  entry = _manifest_entry_for_key(manifest, source_key)
  if not entry:
    return False
  if entry.get("etag") != etag:
    return False
  return entry.get("status") in ("ok", "skipped_too_large", "scan_low_value")


def _entry_to_output(entry: dict, source_key: str, file_name: str, etag: str) -> ProcessOutput:
  meta_data = entry.get("meta")
  if meta_data:
    meta = ParsedDocumentMeta.model_validate(meta_data)
  else:
    meta = ParsedDocumentMeta(
      doc_id=entry.get("doc_id", ""),
      file_name=file_name,
      source_key=source_key,
      file_hash=entry.get("file_hash", etag),
      chunks=entry.get("chunks", 0),
      tables=entry.get("tables", 0),
      ocr_pages=entry.get("ocr_pages", 0),
      noise_blocks_dropped=entry.get("noise_blocks_dropped", 0),
      status=entry.get("status", "ok"),
      error=entry.get("error"),
    )
  return ProcessOutput(
    file_hash=entry.get("file_hash", etag),
    doc_id=entry.get("doc_id", ""),
    source_key=source_key,
    file_name=file_name,
    etag=etag,
    meta=meta,
    processing_seconds=entry.get("processing_seconds", 0.0),
  )


def process_local_file(
  local_path: Path,
  *,
  source_key: str,
  file_name: str,
  etag: str,
  parsed_dir: Path,
) -> ProcessOutput:
  started = time.perf_counter()
  file_hash = file_sha256(local_path)
  doc_id = doc_id_from_hash(file_hash)

  def _write_meta(meta: ParsedDocumentMeta) -> None:
    meta_path = parsed_dir / f"{doc_id}.meta.json"
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

  if local_path.stat().st_size > MAX_FILE_BYTES:
    meta = ParsedDocumentMeta(
      doc_id=doc_id,
      file_name=file_name,
      source_key=source_key,
      file_hash=file_hash,
      chunks=0,
      tables=0,
      ocr_pages=0,
      noise_blocks_dropped=0,
      status="skipped_too_large",
      error=f"File size exceeds {MAX_FILE_BYTES} bytes",
      processing_seconds=time.perf_counter() - started,
    )
    _write_meta(meta)
    return ProcessOutput(
      file_hash=file_hash,
      doc_id=doc_id,
      source_key=source_key,
      file_name=file_name,
      etag=etag,
      meta=meta,
      processing_seconds=meta.processing_seconds or 0.0,
    )

  if local_path.suffix.lower() == ".pdf":
    pages = count_pdf_pages(local_path)
    if pages > MAX_PDF_PAGES:
      meta = ParsedDocumentMeta(
        doc_id=doc_id,
        file_name=file_name,
        source_key=source_key,
        file_hash=file_hash,
        pages=pages,
        chunks=0,
        tables=0,
        ocr_pages=0,
        noise_blocks_dropped=0,
        status="skipped_too_large",
        error=f"PDF has {pages} pages (limit {MAX_PDF_PAGES})",
        processing_seconds=time.perf_counter() - started,
      )
      _write_meta(meta)
      return ProcessOutput(
        file_hash=file_hash,
        doc_id=doc_id,
        source_key=source_key,
        file_name=file_name,
        etag=etag,
        meta=meta,
        processing_seconds=meta.processing_seconds or 0.0,
      )

  try:
    result, noise_dropped, reference_texts = parse_file(local_path)
    source_meta = parse_source_key(source_key)
    author_hint = extract_author_hint(file_name)
    chunks = blocks_to_chunks(
      result.blocks,
      doc_id=doc_id,
      file_name=file_name,
      source_key=source_key,
      author_hint=author_hint,
      venue=source_meta.venue,
      year=source_meta.year,
      doc_type=source_meta.doc_type,
    )
    chunk_ids = [c.chunk_id for c in chunks]
    assert len(chunk_ids) == len(set(chunk_ids)), (
      f"Duplicate chunk_id in {file_name}: "
      f"{[cid for cid in chunk_ids if chunk_ids.count(cid) > 1]}"
    )
    tables = sum(1 for c in chunks if c.kind == "table")
    pages = result.doc_meta.pages
    text_chars = sum(len(c.text) for c in chunks)
    text_chunks = [c for c in chunks if c.kind == "text"]
    avg_chunk_chars = (
      sum(len(c.text) for c in text_chunks) / len(text_chunks) if text_chunks else None
    )
    text_chars_per_page = text_chars / pages if pages else None
    low_yield = text_chars_per_page is not None and text_chars_per_page < 150
    status: str = "ok"
    if result.doc_meta.scan_low_value:
      status = "scan_low_value"

    jsonl_path = parsed_dir / f"{doc_id}.jsonl"
    refs_path = parsed_dir / f"{doc_id}.references.json"

    write_jsonl(chunks, jsonl_path)
    write_references(reference_texts, refs_path)

    elapsed = time.perf_counter() - started
    meta = ParsedDocumentMeta(
      doc_id=doc_id,
      file_name=file_name,
      source_key=source_key,
      file_hash=file_hash,
      file_metadata_author=result.doc_meta.file_metadata_author,
      author_hint=author_hint,
      created=result.doc_meta.created,
      pages=pages,
      chunks=len(chunks),
      tables=tables,
      ocr_pages=result.doc_meta.ocr_pages,
      ocr_skipped_pages=result.doc_meta.ocr_skipped_pages,
      ocr_low_yield_pages=result.doc_meta.ocr_low_yield_pages,
      noise_blocks_dropped=noise_dropped,
      text_chars=text_chars,
      text_chars_per_page=text_chars_per_page,
      avg_chunk_chars=avg_chunk_chars,
      low_yield=low_yield,
      category=source_meta.category,
      venue=source_meta.venue,
      year=source_meta.year,
      doc_type=source_meta.doc_type,
      status=status,
      processing_seconds=elapsed,
    )
    _write_meta(meta)

    return ProcessOutput(
      file_hash=file_hash,
      doc_id=doc_id,
      source_key=source_key,
      file_name=file_name,
      etag=etag,
      meta=meta,
      processing_seconds=elapsed,
    )
  except Exception as exc:
    elapsed = time.perf_counter() - started
    meta = ParsedDocumentMeta(
      doc_id=doc_id,
      file_name=file_name,
      source_key=source_key,
      file_hash=file_hash,
      chunks=0,
      tables=0,
      ocr_pages=0,
      noise_blocks_dropped=0,
      status="error",
      error=str(exc),
      processing_seconds=elapsed,
    )
    _write_meta(meta)
    logger.error("Failed %s: %s\n%s", file_name, exc, traceback.format_exc())
    return ProcessOutput(
      file_hash=file_hash,
      doc_id=doc_id,
      source_key=source_key,
      file_name=file_name,
      etag=etag,
      meta=meta,
      processing_seconds=elapsed,
    )


def _upload_outputs(storage, parsed_dir: Path, doc_id: str, has_references: bool) -> None:
  if not storage.available:
    return
  for suffix in (".jsonl", ".meta.json"):
    local = parsed_dir / f"{doc_id}{suffix}"
    if local.exists():
      storage.upload_file(local, f"parsed/{doc_id}{suffix}")
  if has_references:
    refs = parsed_dir / f"{doc_id}.references.json"
    if refs.exists():
      storage.upload_file(refs, f"parsed/{doc_id}.references.json")


def _collect_jobs(
  corpus_prefix: str,
  manifest: dict,
  *,
  force: bool,
) -> tuple[list[FileJob], list[ProcessOutput]]:
  storage = get_storage()
  skipped_outputs: list[ProcessOutput] = []
  jobs: list[FileJob] = []

  if storage.available:
    for obj in storage.list_objects(corpus_prefix):
      suffix = Path(obj.key).suffix.lower()
      if suffix not in SUPPORTED_SUFFIXES:
        continue
      file_name = Path(obj.key).name
      if _should_skip_by_key(manifest, obj.key, obj.etag, force=force):
        entry = _manifest_entry_for_key(manifest, obj.key)
        if entry:
          skipped_outputs.append(_entry_to_output(entry, obj.key, file_name, obj.etag))
        continue
      if obj.size > MAX_FILE_BYTES:
        doc_id = f"doc_size_{obj.etag[:8]}"
        skipped_outputs.append(
          ProcessOutput(
            file_hash=obj.etag,
            doc_id=doc_id,
            source_key=obj.key,
            file_name=file_name,
            etag=obj.etag,
            meta=ParsedDocumentMeta(
              doc_id=doc_id,
              file_name=file_name,
              source_key=obj.key,
              file_hash=obj.etag,
              chunks=0,
              tables=0,
              ocr_pages=0,
              noise_blocks_dropped=0,
              status="skipped_too_large",
              error=f"File size {obj.size} exceeds {MAX_FILE_BYTES}",
            ),
            processing_seconds=0.0,
          )
        )
        continue
      jobs.append(
        FileJob(
          source_key=obj.key,
          file_name=file_name,
          etag=obj.etag,
          size=obj.size,
        )
      )
  else:
    local_root = REPO_ROOT / "data" / corpus_prefix.removeprefix("raw/")
    search_dirs = [local_root, REPO_ROOT / "data" / "raw"]
    seen: set[Path] = set()
    for base in search_dirs:
      if not base.exists():
        continue
      for path in list(base.rglob("*.pdf")) + list(base.rglob("*.docx")):
        if path in seen:
          continue
        seen.add(path)
        rel = path.relative_to(REPO_ROOT / "data")
        source_key = f"raw/{rel.as_posix()}"
        file_hash = file_sha256(path)
        if _should_skip_by_key(manifest, source_key, file_hash, force=force):
          entry = _manifest_entry_for_key(manifest, source_key)
          if entry:
            skipped_outputs.append(
              _entry_to_output(entry, source_key, path.name, file_hash)
            )
          continue
        if path.stat().st_size > MAX_FILE_BYTES:
          continue
        jobs.append(
          FileJob(
            source_key=source_key,
            file_name=path.name,
            etag=file_hash,
            size=path.stat().st_size,
            local_path=path,
          )
        )

  return jobs, skipped_outputs


def _manifest_record(output: ProcessOutput) -> dict:
  return {
    "doc_id": output.doc_id,
    "source_key": output.source_key,
    "file_name": output.file_name,
    "etag": output.etag,
    "file_hash": output.file_hash,
    "status": output.meta.status,
    "chunks": output.meta.chunks,
    "tables": output.meta.tables,
    "ocr_pages": output.meta.ocr_pages,
    "noise_blocks_dropped": output.meta.noise_blocks_dropped,
    "processing_seconds": output.processing_seconds,
    "meta": output.meta.model_dump(),
  }


def _print_summary(outputs: list[ProcessOutput], total_seconds: float, parsed_dir: Path) -> None:
  print("\n=== Ingest summary ===")
  print(
    f"{'Document':<36} {'Chunks':>7} {'AvgChr':>7} {'Tables':>7} "
    f"{'OCR':>5} {'Noise':>7} {'Status':>14}"
  )
  print("-" * 90)
  low_yield_docs: list[str] = []
  scan_low_value_docs: list[str] = []
  for out in outputs:
    m = out.meta
    avg_chars = f"{m.avg_chunk_chars:.0f}" if m.avg_chunk_chars is not None else "-"
    print(
      f"{out.file_name:<36} {m.chunks:>7} {avg_chars:>7} {m.tables:>7} "
      f"{m.ocr_pages:>5} {m.noise_blocks_dropped:>7} {m.status:>14}"
    )
    if m.status == "ok" and m.pages and m.pages > 0 and m.chunks / m.pages > 6:
      logger.warning(
        "High chunk density: %s (%d chunks / %d pages)",
        out.file_name,
        m.chunks,
        m.pages,
      )
    if m.avg_chunk_chars is not None and (
      m.avg_chunk_chars < 600 or m.avg_chunk_chars > 2500
    ):
      logger.warning(
        "Unusual avg chunk size: %s (avg_chunk_chars=%.0f)",
        out.file_name,
        m.avg_chunk_chars,
      )
    if m.low_yield:
      low_yield_docs.append(out.file_name)
    if m.status == "scan_low_value":
      scan_low_value_docs.append(out.file_name)

  ok_count = sum(1 for o in outputs if o.meta.status == "ok")
  print("-" * 90)
  print(f"Total files: {len(outputs)} (ok: {ok_count})")
  print(f"Total time: {total_seconds:.1f}s")
  if total_seconds > 0 and outputs:
    print(f"Throughput: {len(outputs) / (total_seconds / 60):.1f} files/min")

  if low_yield_docs:
    print("\nLow-yield documents:")
    for name in low_yield_docs:
      print(f"  {name}")

  if scan_low_value_docs:
    print("\nScan low-value documents:")
    for name in scan_low_value_docs:
      print(f"  {name}")

  slowest = sorted(outputs, key=lambda o: o.processing_seconds, reverse=True)[:5]
  if slowest:
    print("\nTop 5 slowest:")
    for out in slowest:
      print(f"  {out.file_name}: {out.processing_seconds:.1f}s")

  all_chunk_ids: list[str] = []
  for out in outputs:
    if out.meta.status not in ("ok", "scan_low_value"):
      continue
    jsonl_path = parsed_dir / f"{out.doc_id}.jsonl"
    if not jsonl_path.exists():
      continue
    with jsonl_path.open(encoding="utf-8") as f:
      for line in f:
        if line.strip():
          record = json.loads(line)
          all_chunk_ids.append(record["chunk_id"])
  duplicate_count = len(all_chunk_ids) - len(set(all_chunk_ids))
  print(
    f"\nUnique chunk_ids: {len(all_chunk_ids)} total, "
    f"{duplicate_count} duplicates"
  )
  if duplicate_count:
    raise AssertionError(f"Found {duplicate_count} duplicate chunk_ids across corpus")


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Ingest PDF/DOCX corpus into ParsedChunk JSONL")
  parser.add_argument("--workers", type=int, default=8)
  parser.add_argument("--corpus-prefix", default=DEFAULT_CORPUS_PREFIX)
  parser.add_argument(
    "--parsed-dir",
    type=Path,
    default=DATA_PARSED,
    help="Output directory for parsed JSONL",
  )
  parser.add_argument(
    "--force",
    action="store_true",
    help="Reprocess all documents ignoring manifest cache",
  )
  args = parser.parse_args(argv)

  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

  parsed_dir = args.parsed_dir
  parsed_dir.mkdir(parents=True, exist_ok=True)
  manifest_path = parsed_dir / MANIFEST_NAME
  manifest = load_manifest(manifest_path)

  storage = get_storage()
  jobs, already_done = _collect_jobs(args.corpus_prefix, manifest, force=args.force)

  all_outputs: list[ProcessOutput] = list(already_done)
  started = time.perf_counter()
  completed_since_flush = 0

  if not jobs:
    logger.info("No new files to ingest (%d already done)", len(already_done))
    _print_summary(all_outputs, time.perf_counter() - started, parsed_dir)
    return 0

  with ProcessPoolExecutor(max_workers=args.workers) as pool:
    pending = list(jobs)
    futures: dict = {}
    pbar = tqdm(total=len(jobs), desc="Processing")

    while pending or futures:
      while pending and len(futures) < args.workers:
        job = pending.pop(0)
        if job.local_path:
          local_path = job.local_path
        else:
          suffix = Path(job.file_name).suffix
          tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
          tmp.close()
          local_path = Path(tmp.name)
          storage.download_file(job.source_key, local_path)

        future = pool.submit(
          process_local_file,
          local_path,
          source_key=job.source_key,
          file_name=job.file_name,
          etag=job.etag,
          parsed_dir=parsed_dir,
        )
        futures[future] = (job, local_path)

      if not futures:
        break

      done, _ = wait(futures, return_when=FIRST_COMPLETED)
      for future in done:
        job, local_path = futures.pop(future)
        pbar.update(1)
        try:
          output = future.result()
        except Exception as exc:
          logger.error("Worker failed for %s: %s", job.file_name, exc)
          output = ProcessOutput(
            file_hash=job.etag,
            doc_id=doc_id_from_hash(job.etag),
            source_key=job.source_key,
            file_name=job.file_name,
            etag=job.etag,
            meta=ParsedDocumentMeta(
              doc_id=doc_id_from_hash(job.etag),
              file_name=job.file_name,
              source_key=job.source_key,
              file_hash=job.etag,
              chunks=0,
              tables=0,
              ocr_pages=0,
              noise_blocks_dropped=0,
              status="error",
              error=str(exc),
            ),
            processing_seconds=0.0,
          )

        all_outputs.append(output)
        manifest[output.file_hash] = _manifest_record(output)

        if output.meta.status in ("ok", "scan_low_value"):
          refs_path = parsed_dir / f"{output.doc_id}.references.json"
          _upload_outputs(storage, parsed_dir, output.doc_id, refs_path.exists())

        if job.local_path is None and local_path.exists():
          local_path.unlink(missing_ok=True)

        completed_since_flush += 1
        if completed_since_flush >= MANIFEST_FLUSH_EVERY:
          save_manifest(manifest_path, manifest)
          completed_since_flush = 0

    pbar.close()

  save_manifest(manifest_path, manifest)
  _print_summary(all_outputs, time.perf_counter() - started, parsed_dir)
  return 0


if __name__ == "__main__":
  sys.exit(main())
