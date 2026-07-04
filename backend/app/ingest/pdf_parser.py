"""Парсинг PDF через PyMuPDF, pdfplumber и Tesseract."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import fitz
import pdfplumber
import pytesseract
from pytesseract import TesseractNotFoundError

from app.ingest.types import Block, DocMeta, ParseResult

logger = logging.getLogger(__name__)

_TEXT_LAYER_MIN_CHARS = 200
_HEADING_MAX_LEN = 80
_BOLD_FLAG = 16  # fitz TEXT_FONT_BOLD
_tesseract_warned = False


def _tesseract_available() -> bool:
  return shutil.which("tesseract") is not None


def _warn_tesseract_missing() -> None:
  global _tesseract_warned
  if not _tesseract_warned:
    logger.warning(
      "tesseract not found in PATH — OCR pages will be skipped. "
      "Install: apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng"
    )
    _tesseract_warned = True


def _span_font_size(span: dict) -> float:
  return float(span.get("size", 0))


def _blocks_from_dict(page_dict: dict, page_num: int) -> list[dict]:
  items: list[dict] = []
  for block in page_dict.get("blocks", []):
    if block.get("type") != 0:
      continue
    lines = block.get("lines", [])
    parts: list[str] = []
    sizes: list[float] = []
    bold = False
    for line in lines:
      for span in line.get("spans", []):
        text = span.get("text", "")
        if text:
          parts.append(text)
          sizes.append(_span_font_size(span))
          if span.get("flags", 0) & _BOLD_FLAG:
            bold = True
    text = " ".join(parts).strip()
    if not text:
      continue
    bbox = block.get("bbox", (0, 0, 0, 0))
    avg_size = sum(sizes) / len(sizes) if sizes else 0.0
    items.append(
      {
        "text": text,
        "bbox": bbox,
        "page": page_num,
        "font_size": avg_size,
        "bold": bold,
        "y0": bbox[1],
        "x0": bbox[0],
      }
    )
  items.sort(key=lambda b: (b["y0"], b["x0"]))
  return items


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
  return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _intersection_area(
  a: tuple[float, float, float, float],
  b: tuple[float, float, float, float],
) -> float:
  x0 = max(a[0], b[0])
  y0 = max(a[1], b[1])
  x1 = min(a[2], b[2])
  y1 = min(a[3], b[3])
  if x1 <= x0 or y1 <= y0:
    return 0.0
  return (x1 - x0) * (y1 - y0)


def _overlaps_table(
  block_bbox: tuple[float, float, float, float],
  table_bboxes: list[tuple[float, float, float, float]],
  threshold: float = 0.3,
) -> bool:
  block_area = _bbox_area(block_bbox)
  if block_area <= 0:
    return False
  for tb in table_bboxes:
    inter = _intersection_area(block_bbox, tb)
    if inter / block_area > threshold:
      return True
  return False


def _table_rows_to_markdown(rows: list[list[str | None]]) -> str:
  if not rows:
    return ""
  str_rows = [[("" if c is None else str(c)).strip() for c in row] for row in rows]
  width = max((len(r) for r in str_rows), default=0)
  if width == 0:
    return ""
  header = str_rows[0] if str_rows else [f"col{i + 1}" for i in range(width)]
  header = header + [""] * (width - len(header))
  lines = [
    "| " + " | ".join(header) + " |",
    "| " + " | ".join("---" for _ in header) + " |",
  ]
  for row in str_rows[1:]:
    padded = row + [""] * (width - len(row))
    lines.append("| " + " | ".join(padded[:width]) + " |")
  return "\n".join(lines)


def _ocr_page(page: fitz.Page) -> str | None:
  if not _tesseract_available():
    _warn_tesseract_missing()
    return None
  import tempfile

  pix = page.get_pixmap(dpi=300)
  with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
    pix.save(tmp.name)
    try:
      return pytesseract.image_to_string(tmp.name, lang="rus+eng")
    except TesseractNotFoundError:
      _warn_tesseract_missing()
      return None


def parse_pdf(path: Path) -> ParseResult:
  doc = fitz.open(str(path))
  all_font_sizes: list[float] = []
  page_text_blocks: dict[int, list[dict]] = {}
  ocr_pages = 0

  for page_index in range(len(doc)):
    page = doc[page_index]
    page_num = page_index + 1
    page_dict = page.get_text("dict")
    text_len = sum(
      len(span.get("text", ""))
      for block in page_dict.get("blocks", [])
      if block.get("type") == 0
      for line in block.get("lines", [])
      for span in line.get("spans", [])
    )

    if text_len > _TEXT_LAYER_MIN_CHARS:
      blocks = _blocks_from_dict(page_dict, page_num)
      for b in blocks:
        if b["font_size"] > 0:
          all_font_sizes.append(b["font_size"])
      page_text_blocks[page_num] = blocks
    else:
      logger.warning("OCR page %d in %s", page_num, path.name)
      ocr_pages += 1
      ocr_text = (_ocr_page(page) or "").strip()
      if ocr_text:
        page_text_blocks[page_num] = [
          {
            "text": ocr_text,
            "bbox": page.rect,
            "page": page_num,
            "font_size": 0.0,
            "bold": False,
            "y0": 0.0,
            "x0": 0.0,
          }
        ]

  median_font = sorted(all_font_sizes)[len(all_font_sizes) // 2] if all_font_sizes else 12.0

  table_pages: set[int] = set()
  for page_index in range(len(doc)):
    page = doc[page_index]
    try:
      finder = page.find_tables()
      if finder.tables:
        table_pages.add(page_index + 1)
    except Exception:
      pass

  page_tables: dict[int, list[str]] = {}
  table_bboxes_by_page: dict[int, list[tuple[float, float, float, float]]] = {}

  if table_pages:
    with pdfplumber.open(str(path)) as pdf:
      for page_num in sorted(table_pages):
        plumber_page = pdf.pages[page_num - 1]
        found = plumber_page.find_tables()
        bboxes = [t.bbox for t in found]
        table_bboxes_by_page[page_num] = bboxes
        md_tables: list[str] = []
        for table in found:
          rows = table.extract()
          if rows:
            md = _table_rows_to_markdown(rows)
            if md:
              md_tables.append(md)
        if md_tables:
          page_tables[page_num] = md_tables

  blocks: list[Block] = []
  markdown_parts: list[str] = []

  for page_num in sorted(page_text_blocks.keys()):
    text_blocks = page_text_blocks[page_num]
    table_bboxes = table_bboxes_by_page.get(page_num, [])

    for tb in text_blocks:
      if table_bboxes and _overlaps_table(tb["bbox"], table_bboxes):
        continue
      text = tb["text"]
      is_heading = (
        len(text) < _HEADING_MAX_LEN
        and (tb["font_size"] > median_font * 1.2 or tb["bold"])
      )
      if is_heading:
        block = Block(type="heading", text=text, level=2, page=page_num)
        markdown_parts.append(f"## {text}")
      else:
        block = Block(type="paragraph", text=text, page=page_num)
        markdown_parts.append(text)
      blocks.append(block)

    for md in page_tables.get(page_num, []):
      blocks.append(Block(type="table", text=md, page=page_num))
      markdown_parts.append(md)

  meta = doc.metadata or {}
  doc_meta = DocMeta(
    file_metadata_author=meta.get("author") or None,
    created=meta.get("creationDate") or None,
    pages=len(doc),
    ocr_pages=ocr_pages,
    ocr_low_yield_pages=0,
  )
  doc.close()

  return ParseResult(
    markdown_text="\n\n".join(markdown_parts),
    blocks=blocks,
    doc_meta=doc_meta,
  )


def count_pdf_pages(path: Path) -> int:
  doc = fitz.open(str(path))
  try:
    return len(doc)
  finally:
    doc.close()
