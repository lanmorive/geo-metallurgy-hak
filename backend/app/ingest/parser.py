"""Парсинг PDF/DOCX в текст и структурные блоки."""

from __future__ import annotations

import logging
from pathlib import Path

from app.ingest.docx_parser import parse_docx
from app.ingest.noise import is_noise
from app.ingest.pdf_parser import parse_pdf
from app.ingest.pptx_parser import parse_pptx
from app.ingest.sections import assign_sections
from app.ingest.types import Block, ParseResult

logger = logging.getLogger(__name__)


def parse_file(path: Path) -> tuple[ParseResult, int, list[str]]:
  """
  Разобрать PDF, DOCX или PPTX/POTX.

  Returns:
    (ParseResult, noise_blocks_dropped, reference_texts)
  """
  suffix = path.suffix.lower()
  if suffix == ".pdf":
    result = parse_pdf(path)
  elif suffix == ".docx":
    result = parse_docx(path)
  elif suffix in (".pptx", ".potx"):
    result = parse_pptx(path)
  else:
    raise ValueError(f"Unsupported format: {suffix}")

  filtered: list[Block] = []
  noise_dropped = 0
  for block in result.blocks:
    if block.type == "table":
      filtered.append(block)
      continue
    if is_noise(block.text):
      noise_dropped += 1
      continue
    filtered.append(block)

  filtered, reference_texts = assign_sections(filtered)
  result.blocks = filtered
  return result, noise_dropped, reference_texts
