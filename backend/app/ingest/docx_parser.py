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

from app.ingest.authors import fix_file_metadata_author
from app.ingest.table_md import dedup_row_cells, rows_to_markdown
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


def _row_cells(row) -> list[str]:
  return dedup_row_cells([_cell_text(cell) for cell in row.cells])


def _table_to_markdown(table: Table) -> str:
  rows = list(table.rows)
  if not rows:
    return ""
  parsed_rows = [_row_cells(row) for row in rows]
  return rows_to_markdown(parsed_rows)


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
    file_metadata_author=fix_file_metadata_author(props.author),
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
