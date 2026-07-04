"""Парсинг PDF через PyMuPDF, pdfplumber и Tesseract."""

from __future__ import annotations

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import fitz
import pdfplumber
import pytesseract
from pytesseract import TesseractNotFoundError

from app.ingest.authors import fix_file_metadata_author
from app.ingest.noise import is_noise
from app.ingest.types import Block, DocMeta, ParseResult

logger = logging.getLogger(__name__)

_TEXT_LAYER_MIN_CHARS = 200
_OCR_LOW_YIELD_MIN_CHARS = 100
_SCAN_PROBE_MIN_CHARS = 200
_SCAN_PROBE_PAGES = 3
_HEADING_MAX_LEN = 80
_HEADING_FONT_RATIO = 1.25
_HEADING_MAX_PER_PAGE = 3
_COLUMN_GAP_RATIO = 0.15
_BOLD_FLAG = 16  # fitz TEXT_FONT_BOLD
OCR_DPI = 220
OCR_POOL_SIZE = 4
_tesseract_warned = False


@dataclass
class _PageInfo:
  page_index: int
  page_num: int
  text_len: int
  has_images: bool
  page_dict: dict
  page_width: float


@dataclass
class _OcrJob:
  page_index: int
  page_num: int
  check_low_yield: bool


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


def _sort_blocks_reading_order(
  items: list[dict],
  page_width: float,
) -> list[dict]:
  if len(items) < 4 or page_width <= 0:
    return sorted(items, key=lambda b: (b["y0"], b["x0"]))

  x0s = sorted(b["x0"] for b in items)
  max_gap = 0.0
  split_at: float | None = None
  for i in range(len(x0s) - 1):
    gap = x0s[i + 1] - x0s[i]
    if gap > max_gap:
      max_gap = gap
      split_at = (x0s[i] + x0s[i + 1]) / 2

  if max_gap < page_width * _COLUMN_GAP_RATIO or split_at is None:
    return sorted(items, key=lambda b: (b["y0"], b["x0"]))

  left = sorted((b for b in items if b["x0"] < split_at), key=lambda b: b["y0"])
  right = sorted((b for b in items if b["x0"] >= split_at), key=lambda b: b["y0"])
  return left + right


def _blocks_from_dict(page_dict: dict, page_num: int, page_width: float) -> list[dict]:
  items: list[dict] = []
  for block in page_dict.get("blocks", []):
    if block.get("type") != 0:
      continue
    lines = block.get("lines", [])
    parts: list[str] = []
    sizes: list[float] = []
    for line in lines:
      for span in line.get("spans", []):
        text = span.get("text", "")
        if text:
          parts.append(text)
          sizes.append(_span_font_size(span))
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
        "y0": bbox[1],
        "x0": bbox[0],
      }
    )
  return _sort_blocks_reading_order(items, page_width)


def _is_heading_candidate(text: str, font_size: float, median_font: float) -> bool:
  return (
    len(text) < _HEADING_MAX_LEN
    and font_size > median_font * _HEADING_FONT_RATIO
    and not text.rstrip().endswith((".", ","))
  )


def _classify_page_blocks(
  text_blocks: list[dict],
  median_font: float,
) -> list[tuple[dict, bool]]:
  candidates = [
    (tb, _is_heading_candidate(tb["text"], tb["font_size"], median_font))
    for tb in text_blocks
  ]
  heading_count = sum(1 for _, is_h in candidates if is_h)
  if heading_count > _HEADING_MAX_PER_PAGE:
    return [(tb, False) for tb, _ in candidates]
  return candidates


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


def _ocr_page(page: fitz.Page, counters: dict[str, int]) -> str | None:
  if not _tesseract_available():
    _warn_tesseract_missing()
    return None
  import tempfile

  pix = page.get_pixmap(dpi=OCR_DPI)
  with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
    pix.save(tmp.name)
    try:
      counters["ocr_pages"] += 1
      return pytesseract.image_to_string(tmp.name, lang="rus+eng")
    except TesseractNotFoundError:
      _warn_tesseract_missing()
      return None


def _page_text_len(page_dict: dict) -> int:
  return sum(
    len(span.get("text", ""))
    for block in page_dict.get("blocks", [])
    if block.get("type") == 0
    for line in block.get("lines", [])
    for span in line.get("spans", [])
  )


def _needs_ocr(info: _PageInfo) -> bool:
  if info.text_len > _TEXT_LAYER_MIN_CHARS:
    return False
  if not info.has_images and info.text_len == 0:
    return False
  return True


def _run_ocr_jobs(
  doc: fitz.Document,
  jobs: list[_OcrJob],
  counters: dict[str, int],
) -> dict[int, tuple[str | None, bool]]:
  """Вернуть page_num -> (ocr_text or None, is_low_yield)."""
  if not jobs:
    return {}

  results: dict[int, tuple[str | None, bool]] = {}

  def _process(job: _OcrJob) -> tuple[int, str | None, bool]:
    page = doc[job.page_index]
    ocr_text = (_ocr_page(page, counters) or "").strip()
    if not ocr_text:
      return job.page_num, None, job.check_low_yield
    if job.check_low_yield and (
      is_noise(ocr_text) or len(ocr_text) < _OCR_LOW_YIELD_MIN_CHARS
    ):
      return job.page_num, None, True
    return job.page_num, ocr_text, False

  if not _tesseract_available():
    _warn_tesseract_missing()
    counters["ocr_skipped_pages"] += len(jobs)
    for job in jobs:
      results[job.page_num] = (None, job.check_low_yield)
    return results

  with ThreadPoolExecutor(max_workers=OCR_POOL_SIZE) as pool:
    futures = {pool.submit(_process, job): job for job in jobs}
    for future in as_completed(futures):
      page_num, ocr_text, is_low_yield = future.result()
      results[page_num] = (ocr_text, is_low_yield)

  return results


def _build_ocr_jobs(pages: list[_PageInfo]) -> list[_OcrJob]:
  jobs: list[_OcrJob] = []
  for info in pages:
    if not _needs_ocr(info):
      continue
    check_low_yield = info.has_images and info.text_len < _TEXT_LAYER_MIN_CHARS
    logger.warning("OCR page %d", info.page_num)
    jobs.append(
      _OcrJob(
        page_index=info.page_index,
        page_num=info.page_num,
        check_low_yield=check_low_yield,
      )
    )
  return jobs


def parse_pdf(path: Path) -> ParseResult:
  doc = fitz.open(str(path))
  counters = {"ocr_pages": 0, "ocr_skipped_pages": 0}
  all_font_sizes: list[float] = []
  page_text_blocks: dict[int, list[dict]] = {}
  ocr_low_yield_pages = 0
  scan_low_value = False

  page_infos: list[_PageInfo] = []
  for page_index in range(len(doc)):
    page = doc[page_index]
    page_num = page_index + 1
    page_dict = page.get_text("dict")
    page_infos.append(
      _PageInfo(
        page_index=page_index,
        page_num=page_num,
        text_len=_page_text_len(page_dict),
        has_images=bool(page.get_images()),
        page_dict=page_dict,
        page_width=page.rect.width,
      )
    )

  fully_scanned = all(p.text_len <= _TEXT_LAYER_MIN_CHARS for p in page_infos)

  for info in page_infos:
    if info.text_len > _TEXT_LAYER_MIN_CHARS:
      blocks = _blocks_from_dict(info.page_dict, info.page_num, info.page_width)
      for b in blocks:
        if b["font_size"] > 0:
          all_font_sizes.append(b["font_size"])
      page_text_blocks[info.page_num] = blocks

  if fully_scanned:
    probe_jobs = [
      _OcrJob(page_index=p.page_index, page_num=p.page_num, check_low_yield=False)
      for p in page_infos
      if p.page_num <= _SCAN_PROBE_PAGES and _needs_ocr(p)
    ]
    if probe_jobs and not _tesseract_available():
      _warn_tesseract_missing()
      counters["ocr_skipped_pages"] += len(probe_jobs)
    elif probe_jobs:
      probe_results = _run_ocr_jobs(doc, probe_jobs, counters)
      probe_text = ""
      for page_num, (ocr_text, is_low_yield) in probe_results.items():
        if is_low_yield:
          ocr_low_yield_pages += 1
          continue
        if ocr_text:
          probe_text += ocr_text
          page = doc[page_num - 1]
          page_text_blocks[page_num] = [
            {
              "text": ocr_text,
              "bbox": page.rect,
              "page": page_num,
              "font_size": 0.0,
              "y0": 0.0,
              "x0": 0.0,
            }
          ]
      if len(probe_text.strip()) < _SCAN_PROBE_MIN_CHARS:
        scan_low_value = True
      else:
        remaining_jobs = [
          _OcrJob(page_index=p.page_index, page_num=p.page_num, check_low_yield=False)
          for p in page_infos
          if p.page_num > _SCAN_PROBE_PAGES and _needs_ocr(p)
        ]
        if remaining_jobs:
          remaining_results = _run_ocr_jobs(doc, remaining_jobs, counters)
          for page_num, (ocr_text, is_low_yield) in remaining_results.items():
            if is_low_yield:
              ocr_low_yield_pages += 1
              continue
            if ocr_text:
              page = doc[page_num - 1]
              page_text_blocks[page_num] = [
                {
                  "text": ocr_text,
                  "bbox": page.rect,
                  "page": page_num,
                  "font_size": 0.0,
                  "y0": 0.0,
                  "x0": 0.0,
                }
              ]
  else:
    ocr_jobs = _build_ocr_jobs(page_infos)
    ocr_results = _run_ocr_jobs(doc, ocr_jobs, counters)
    for page_num, (ocr_text, is_low_yield) in ocr_results.items():
      if is_low_yield:
        ocr_low_yield_pages += 1
        continue
      if ocr_text:
        page = doc[page_num - 1]
        page_text_blocks[page_num] = [
          {
            "text": ocr_text,
            "bbox": page.rect,
            "page": page_num,
            "font_size": 0.0,
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

    filtered_blocks = [
      tb
      for tb in text_blocks
      if not (table_bboxes and _overlaps_table(tb["bbox"], table_bboxes))
    ]
    classified = _classify_page_blocks(filtered_blocks, median_font)

    for tb, is_heading in classified:
      text = tb["text"]
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
    file_metadata_author=fix_file_metadata_author(meta.get("author")),
    created=meta.get("creationDate") or None,
    pages=len(doc),
    ocr_pages=counters["ocr_pages"],
    ocr_skipped_pages=counters["ocr_skipped_pages"],
    ocr_low_yield_pages=ocr_low_yield_pages,
    scan_low_value=scan_low_value,
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
