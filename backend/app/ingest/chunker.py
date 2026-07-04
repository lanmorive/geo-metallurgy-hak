"""Чанкинг блоков и сохранение в data/parsed/."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import langdetect

from app.ingest.types import Block
from app.schemas.ontology import ParsedChunk

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1200
COALESCE_MAX = 1150
COALESCE_MIN_STANDALONE = 40
SLIDE_AVG_BLOCK_LEN = 120
MIN_TEXT_CHUNK = 300
CROSS_SECTION_MERGE_TARGET = 1200


def _detect_lang(text: str) -> str:
  try:
    code = langdetect.detect(text)
    if code.startswith("ru"):
      return "ru"
    if code.startswith("en"):
      return "en"
  except langdetect.LangDetectException:
    pass
  return "ru"


def _is_text_block(block: Block) -> bool:
  return block.type in ("paragraph", "heading")


def _slide_pages(blocks: list[Block]) -> set[int]:
  by_page: dict[int, list[Block]] = {}
  for block in blocks:
    if _is_text_block(block) and block.page is not None:
      by_page.setdefault(block.page, []).append(block)

  slides: set[int] = set()
  for page, page_blocks in by_page.items():
    avg_len = sum(len(b.text) for b in page_blocks) / len(page_blocks)
    if avg_len < SLIDE_AVG_BLOCK_LEN:
      slides.add(page)
  return slides


def _merge_slide_page(blocks: list[Block]) -> Block:
  merged = "\n".join(b.text for b in blocks if b.text.strip())
  first_line = next(
    (line.strip() for line in merged.split("\n") if line.strip()),
    merged[:80],
  )
  return Block(
    type="paragraph",
    text=merged,
    page=blocks[0].page,
    section=first_line,
    level=blocks[0].level,
  )


def _coalesce_section_group(blocks: list[Block]) -> list[Block]:
  if not blocks:
    return []

  merged_blocks: list[Block] = []
  current = blocks[0]
  current_text = current.text

  for block in blocks[1:]:
    candidate = f"{current_text}\n{block.text}"
    if len(candidate) < COALESCE_MAX:
      current_text = candidate
      continue
    merged_blocks.append(
      Block(
        type="paragraph",
        text=current_text,
        page=current.page,
        section=current.section,
        level=current.level,
      )
    )
    current = block
    current_text = block.text

  merged_blocks.append(
    Block(
      type="paragraph",
      text=current_text,
      page=current.page,
      section=current.section,
      level=current.level,
    )
  )
  return merged_blocks


def _coalesce_text_run(blocks: list[Block]) -> list[Block]:
  if not blocks:
    return []

  groups: list[list[Block]] = []
  current_group = [blocks[0]]
  for block in blocks[1:]:
    if block.section == current_group[-1].section:
      current_group.append(block)
    else:
      groups.append(current_group)
      current_group = [block]
  groups.append(current_group)

  result: list[Block] = []
  for group in groups:
    result.extend(_coalesce_section_group(group))
  return result


def _attach_orphans(blocks: list[Block]) -> list[Block]:
  if not blocks:
    return blocks

  result: list[Block] = []
  pending_short: Block | None = None

  for block in blocks:
    if block.type == "table":
      if pending_short is not None:
        result.append(pending_short)
        pending_short = None
      result.append(block)
      continue

    text_block = block
    if pending_short is not None:
      text_block = Block(
        type="paragraph",
        text=f"{pending_short.text}\n{block.text}",
        page=block.page,
        section=block.section,
        level=block.level,
      )
      pending_short = None

    if len(text_block.text.strip()) < COALESCE_MIN_STANDALONE:
      if result and result[-1].type != "table":
        prev = result[-1]
        result[-1] = Block(
          type="paragraph",
          text=f"{prev.text}\n{text_block.text}",
          page=prev.page,
          section=prev.section,
          level=prev.level,
        )
      else:
        pending_short = text_block
      continue

    result.append(text_block)

  if pending_short is not None:
    if result and result[-1].type != "table":
      prev = result[-1]
      result[-1] = Block(
        type="paragraph",
        text=f"{prev.text}\n{pending_short.text}",
        page=prev.page,
        section=prev.section,
        level=prev.level,
      )
    else:
      result.append(pending_short)

  return result


def _coalesce_blocks(blocks: list[Block]) -> list[Block]:
  slide_page_nums = _slide_pages(blocks)
  coalesced: list[Block] = []
  index = 0

  while index < len(blocks):
    block = blocks[index]
    if block.type == "table" or not _is_text_block(block):
      coalesced.append(block)
      index += 1
      continue

    run = [block]
    next_index = index + 1
    while (
      next_index < len(blocks)
      and _is_text_block(blocks[next_index])
      and blocks[next_index].page == block.page
    ):
      run.append(blocks[next_index])
      next_index += 1

    if block.page is not None and block.page in slide_page_nums:
      coalesced.append(_merge_slide_page(run))
    else:
      coalesced.extend(_coalesce_text_run(run))
    index = next_index

  return _attach_orphans(coalesced)


def _merge_two_chunks(first: ParsedChunk, second: ParsedChunk) -> ParsedChunk:
  return first.model_copy(
    update={"text": f"{first.text}\n\n{second.text}".strip()}
  )


def _merge_small_text_chunks(chunks: list[ParsedChunk]) -> list[ParsedChunk]:
  if not chunks:
    return chunks

  merged: list[ParsedChunk] = []
  i = 0
  while i < len(chunks):
    chunk = chunks[i]
    if chunk.kind == "table":
      merged.append(chunk)
      i += 1
      continue

    accumulated = chunk
    j = i + 1
    while len(accumulated.text) < MIN_TEXT_CHUNK and j < len(chunks):
      nxt = chunks[j]
      if nxt.kind == "table":
        break
      candidate = _merge_two_chunks(accumulated, nxt)
      if len(candidate.text) > CROSS_SECTION_MERGE_TARGET and len(accumulated.text) >= MIN_TEXT_CHUNK:
        break
      accumulated = candidate
      j += 1
      if len(accumulated.text) >= MIN_TEXT_CHUNK:
        break

    merged.append(accumulated)
    i = j if j > i + 1 else i + 1

  text_chunks = [c for c in merged if c.kind == "text"]
  if len(text_chunks) <= 1:
    return merged

  result: list[ParsedChunk] = []
  for chunk in merged:
    if chunk.kind == "table":
      result.append(chunk)
      continue
    if len(chunk.text) >= MIN_TEXT_CHUNK:
      result.append(chunk)
      continue
    if result:
      prev = result[-1]
      if prev.kind == "text":
        result[-1] = _merge_two_chunks(prev, chunk)
        continue
    result.append(chunk)

  text_chunks = [c for c in result if c.kind == "text"]
  if len(text_chunks) > 1:
    final: list[ParsedChunk] = []
    for chunk in result:
      if chunk.kind == "text" and len(chunk.text) < MIN_TEXT_CHUNK and final:
        prev = final[-1]
        if prev.kind == "text":
          final[-1] = _merge_two_chunks(prev, chunk)
          continue
      final.append(chunk)
    return final

  return result


def _dedupe_repeated_lines(text: str) -> str:
  seen: set[str] = set()
  kept: list[str] = []
  for line in text.split("\n"):
    key = line.strip()
    if len(key) > 20:
      if key in seen:
        continue
      seen.add(key)
    kept.append(line)
  return "\n".join(kept)


def _renumber_chunk_ids(chunks: list[ParsedChunk], doc_id: str) -> list[ParsedChunk]:
  return [
    chunk.model_copy(update={"chunk_id": f"{doc_id}_{seq:05d}"})
    for seq, chunk in enumerate(chunks)
  ]


def _paragraphs_from_blocks(
  indexed_blocks: list[tuple[int, Block]],
) -> list[tuple[str, int]]:
  paragraphs: list[tuple[str, int]] = []
  for idx, block in indexed_blocks:
    for line in block.text.split("\n"):
      if line.strip():
        paragraphs.append((line, idx))
  return paragraphs


def _chunk_text_length(lines: list[str]) -> int:
  return len("\n".join(lines)) if lines else 0


def _chunk_paragraphs(
  indexed_blocks: list[tuple[int, Block]],
  *,
  doc_id: str,
  file_name: str,
  source_key: str,
  author_hint: str | None,
  venue: str | None,
  year: int | None,
  doc_type: str | None,
) -> list[ParsedChunk]:
  if not indexed_blocks:
    return []

  paragraphs = _paragraphs_from_blocks(indexed_blocks)
  if not paragraphs:
    return []

  block_by_idx = {idx: block for idx, block in indexed_blocks}
  chunks: list[ParsedChunk] = []

  def _emit(batch_indices: list[int]) -> None:
    if not batch_indices:
      return
    lines = [paragraphs[p_idx][0] for p_idx in batch_indices]
    chunk_text = _dedupe_repeated_lines("\n".join(lines).strip())
    if not chunk_text:
      return
    start_idx = paragraphs[batch_indices[0]][1]
    start_block = block_by_idx[start_idx]
    page = next(
      (b.page for i, b in indexed_blocks if i == start_idx and b.page is not None),
      next((b.page for _, b in indexed_blocks if b.page is not None), None),
    )
    chunks.append(
      ParsedChunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}_00000",
        text=chunk_text,
        kind="text",
        section=start_block.section,
        page=page,
        lang=_detect_lang(chunk_text),
        file_name=file_name,
        source_key=source_key,
        author_hint=author_hint,
        venue=venue,
        year=year,
        doc_type=doc_type,
      )
    )

  n = len(paragraphs)
  pos = 0
  pending_overlap: int | None = None
  prev_window_start: int | None = None

  while pending_overlap is not None or pos < n:
    if pending_overlap is not None:
      window_start = pending_overlap
      batch_indices = [pending_overlap]
      pending_overlap = None
      cursor = window_start + 1
    else:
      window_start = pos
      batch_indices = []
      cursor = pos

    if prev_window_start is not None and window_start <= prev_window_start:
      logger.error(
        "Chunk window did not advance for %s: %s -> %s",
        doc_id,
        prev_window_start,
        window_start,
      )
      break
    prev_window_start = window_start

    if not batch_indices:
      if cursor >= n:
        break
      batch_indices = [cursor]
      cursor += 1

    if len(batch_indices) == 1 and len(paragraphs[batch_indices[0]][0]) >= CHUNK_SIZE:
      _emit(batch_indices)
      pos = cursor
      continue

    while cursor < n:
      trial_lines = [paragraphs[p_idx][0] for p_idx in batch_indices + [cursor]]
      if batch_indices and _chunk_text_length(trial_lines) >= CHUNK_SIZE:
        break
      batch_indices.append(cursor)
      cursor += 1

    _emit(batch_indices)
    pos = cursor

    if pos >= n:
      break

    if len(batch_indices) > 1:
      pending_overlap = batch_indices[-1]
    else:
      pending_overlap = None

  return chunks


def blocks_to_chunks(
  blocks: list[Block],
  *,
  doc_id: str,
  file_name: str,
  source_key: str,
  author_hint: str | None = None,
  venue: str | None = None,
  year: int | None = None,
  doc_type: str | None = None,
) -> list[ParsedChunk]:
  """Разбить блоки на ParsedChunk (таблицы — атомарные чанки)."""
  chunkable = [b for b in blocks if b.section != "references"]
  chunkable = _coalesce_blocks(chunkable)
  chunks: list[ParsedChunk] = []
  text_run: list[tuple[int, Block]] = []
  prev_paragraph: str | None = None

  def _flush_text_run() -> None:
    nonlocal text_run
    if text_run:
      chunks.extend(
        _chunk_paragraphs(
          text_run,
          doc_id=doc_id,
          file_name=file_name,
          source_key=source_key,
          author_hint=author_hint,
          venue=venue,
          year=year,
          doc_type=doc_type,
        )
      )
      text_run = []

  for idx, block in enumerate(chunkable):
    if block.type == "table":
      _flush_text_run()
      context = prev_paragraph or ""
      text = f"{context}\n\n{block.text}".strip() if context else block.text
      text = _dedupe_repeated_lines(text)
      chunks.append(
        ParsedChunk(
          doc_id=doc_id,
          chunk_id=f"{doc_id}_00000",
          text=text,
          kind="table",
          section=block.section,
          page=block.page,
          lang=_detect_lang(block.text),
          file_name=file_name,
          source_key=source_key,
          author_hint=author_hint,
          venue=venue,
          year=year,
          doc_type=doc_type,
        )
      )
      prev_paragraph = None
      continue

    if block.type == "paragraph":
      text_run.append((idx, block))
      prev_paragraph = block.text

  _flush_text_run()
  merged = _merge_small_text_chunks(chunks)
  return _renumber_chunk_ids(merged, doc_id)


def write_jsonl(chunks: list[ParsedChunk], out_path: Path) -> None:
  out_path.parent.mkdir(parents=True, exist_ok=True)
  with out_path.open("w", encoding="utf-8") as f:
    for chunk in chunks:
      f.write(chunk.model_dump_json() + "\n")
  logger.info("Wrote %d chunks to %s", len(chunks), out_path)


def write_references(reference_texts: list[str], out_path: Path) -> None:
  if not reference_texts:
    return
  out_path.parent.mkdir(parents=True, exist_ok=True)
  with out_path.open("w", encoding="utf-8") as f:
    json.dump(reference_texts, f, ensure_ascii=False, indent=2)
