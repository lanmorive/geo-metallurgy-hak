"""Парсинг DOCX через python-docx."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingest.types import Block, DocMeta, ParseResult

_HEADING_RE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)


def _iter_block_items(parent: DocumentType) -> list[Paragraph | Table]:
  items: list[Paragraph | Table] = []
  body = parent.element.body
  for child in body.iterchildren():
    if isinstance(child, CT_P):
      items.append(Paragraph(child, parent))
    elif isinstance(child, CT_Tbl):
      items.append(Table(child, parent))
  return items


def _cell_text(cell) -> str:
  return cell.text.strip()


def _dedup_row_cells(cells: list[str]) -> list[str]:
  if not cells:
    return cells
  result = [cells[0]]
  for cell in cells[1:]:
    if cell != result[-1]:
      result.append(cell)
  return result


def _row_cells(row) -> list[str]:
  return _dedup_row_cells([_cell_text(cell) for cell in row.cells])


def _is_header_row(row) -> bool:
  texts = [_cell_text(cell) for cell in row.cells]
  if not any(texts):
    return False
  non_empty = [t for t in texts if t]
  if not non_empty:
    return False
  alpha_ratio = sum(1 for t in non_empty if any(c.isalpha() for c in t)) / len(
    non_empty
  )
  return alpha_ratio >= 0.5


def _merge_header_rows(row0: list[str], row1: list[str]) -> list[str]:
  width = max(len(row0), len(row1))
  merged: list[str] = []
  for i in range(width):
    a = row0[i] if i < len(row0) else ""
    b = row1[i] if i < len(row1) else ""
    if a and b and a != b:
      merged.append(f"{a} / {b}")
    else:
      merged.append(a or b)
  return merged


def _table_to_markdown(table: Table) -> str:
  rows = list(table.rows)
  if not rows:
    return ""

  parsed_rows = [_row_cells(row) for row in rows]
  header: list[str] | None = None
  data_rows = parsed_rows

  if len(parsed_rows) >= 2 and _is_header_row(rows[0]) and _is_header_row(rows[1]):
    header = _merge_header_rows(parsed_rows[0], parsed_rows[1])
    data_rows = parsed_rows[2:]
  elif len(parsed_rows) >= 1 and _is_header_row(rows[0]):
    header = parsed_rows[0]
    data_rows = parsed_rows[1:]

  if not header:
    width = max((len(r) for r in parsed_rows), default=0)
    header = [f"col{i + 1}" for i in range(width)]
    data_rows = parsed_rows

  lines = [
    "| " + " | ".join(header) + " |",
    "| " + " | ".join("---" for _ in header) + " |",
  ]
  for row in data_rows:
    padded = row + [""] * (len(header) - len(row))
    lines.append("| " + " | ".join(padded[: len(header)]) + " |")
  return "\n".join(lines)


def _paragraph_kind(paragraph: Paragraph) -> tuple[str, int | None]:
  style_name = (paragraph.style.name or "") if paragraph.style else ""
  match = _HEADING_RE.match(style_name)
  if match:
    return "heading", int(match.group(1))
  return "paragraph", None


def parse_docx(path: Path) -> ParseResult:
  document = Document(str(path))
  blocks: list[Block] = []
  markdown_parts: list[str] = []

  props = document.core_properties
  created = props.created.isoformat() if props.created else None
  doc_meta = DocMeta(
    file_metadata_author=props.author or None,
    created=created,
    pages=None,
  )

  for item in _iter_block_items(document):
    if isinstance(item, Paragraph):
      text = item.text.strip()
      if not text:
        continue
      kind, level = _paragraph_kind(item)
      block = Block(type=kind, text=text, level=level, page=None)
      blocks.append(block)
      if kind == "heading":
        markdown_parts.append(f"{'#' * (level or 1)} {text}")
      else:
        markdown_parts.append(text)
    elif isinstance(item, Table):
      md = _table_to_markdown(item)
      if not md:
        continue
      blocks.append(Block(type="table", text=md, page=None))
      markdown_parts.append(md)

  return ParseResult(
    markdown_text="\n\n".join(markdown_parts),
    blocks=blocks,
    doc_meta=doc_meta,
  )
