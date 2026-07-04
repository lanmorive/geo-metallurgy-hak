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
CHUNK_OVERLAP = 150
COALESCE_MAX = 900
COALESCE_MIN_STANDALONE = 40
SLIDE_AVG_BLOCK_LEN = 120


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


def _chunk_paragraphs(
  indexed_blocks: list[tuple[int, Block]],
  *,
  doc_id: str,
  section: str,
  file_name: str,
  source_key: str,
  author_hint: str | None,
) -> list[ParsedChunk]:
  if not indexed_blocks:
    return []

  parts: list[str] = []
  part_start_idx: list[int] = []
  for idx, block in indexed_blocks:
    parts.append(block.text)
    part_start_idx.append(idx)

  full_text = "\n\n".join(parts)
  if not full_text.strip():
    return []

  chunks: list[ParsedChunk] = []
  offsets = []
  pos = 0
  for i, part in enumerate(parts):
    offsets.append((pos, part_start_idx[i]))
    pos += len(part) + 2

  start = 0
  text_len = len(full_text)

  while start < text_len:
    end = min(start + CHUNK_SIZE, text_len)
    if end < text_len:
      boundary = full_text.rfind("\n\n", start, end)
      if boundary > start:
        end = boundary
      else:
        boundary = full_text.rfind("\n", start, end)
        if boundary > start:
          end = boundary

    chunk_text = full_text[start:end].strip()
    if chunk_text:
      start_idx = indexed_blocks[0][0]
      for off, block_idx in reversed(offsets):
        if off <= start:
          start_idx = block_idx
          break
      page = next(
        (b.page for i, b in indexed_blocks if i == start_idx and b.page is not None),
        next((b.page for _, b in indexed_blocks if b.page is not None), None),
      )
      chunks.append(
        ParsedChunk(
          doc_id=doc_id,
          chunk_id=f"{doc_id}_{start_idx:05d}",
          text=chunk_text,
          kind="text",
          section=section,
          page=page,
          lang=_detect_lang(chunk_text),
          file_name=file_name,
          source_key=source_key,
          author_hint=author_hint,
        )
      )

    if end >= text_len:
      break
    start = max(end - CHUNK_OVERLAP, start + 1)

  return chunks


def blocks_to_chunks(
  blocks: list[Block],
  *,
  doc_id: str,
  file_name: str,
  source_key: str,
  author_hint: str | None = None,
) -> list[ParsedChunk]:
  """Разбить блоки на ParsedChunk (таблицы — атомарные чанки)."""
  chunkable = [b for b in blocks if b.section != "references"]
  chunkable = _coalesce_blocks(chunkable)
  chunks: list[ParsedChunk] = []

  prev_paragraph: str | None = None
  for idx, block in enumerate(chunkable):
    if block.type == "table":
      context = prev_paragraph or ""
      text = f"{context}\n\n{block.text}".strip() if context else block.text
      chunks.append(
        ParsedChunk(
          doc_id=doc_id,
          chunk_id=f"{doc_id}_{idx:05d}",
          text=text,
          kind="table",
          section=block.section,
          page=block.page,
          lang=_detect_lang(block.text),
          file_name=file_name,
          source_key=source_key,
          author_hint=author_hint,
        )
      )
      prev_paragraph = None
      continue

    if block.type == "paragraph":
      prev_paragraph = block.text

  text_sections: dict[str, list[tuple[int, Block]]] = {}
  for idx, block in enumerate(chunkable):
    if block.type in ("paragraph", "heading"):
      text_sections.setdefault(block.section, []).append((idx, block))

  for section, indexed in text_sections.items():
    chunks.extend(
      _chunk_paragraphs(
        indexed,
        doc_id=doc_id,
        section=section,
        file_name=file_name,
        source_key=source_key,
        author_hint=author_hint,
      )
    )

  chunks.sort(key=lambda c: c.chunk_id)
  return chunks


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
