"""Парсинг метаданных публикации из S3 source_key."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SOURCES_MARKER = "Источники информации/"

_CATEGORY_DOC_TYPES: dict[str, str] = {
  "Доклады": "presentation",
  "Статьи": "article",
  "Справочники": "reference",
  "Нормативы": "reference",
  "Отчёты": "report",
  "Отчеты": "report",
}


@dataclass
class SourceMeta:
  category: str | None = None
  venue: str | None = None
  year: int | None = None
  doc_type: str = "report"


def parse_source_key(source_key: str) -> SourceMeta:
  """Извлечь category, venue, year, doc_type из пути в S3."""
  marker_pos = source_key.find(_SOURCES_MARKER)
  if marker_pos < 0:
    return SourceMeta()

  tail = source_key[marker_pos + len(_SOURCES_MARKER) :]
  parts = [p for p in tail.split("/") if p]
  if not parts:
    return SourceMeta()

  category = parts[0]

  if category == "Журналы" and len(parts) >= 3:
    year_str = parts[2]
    year = int(year_str) if re.fullmatch(r"\d{4}", year_str) else None
    return SourceMeta(
      category=category,
      venue=parts[1],
      year=year,
      doc_type="journal_issue",
    )

  if category == "Доклады":
    return SourceMeta(category=category, doc_type="presentation")

  doc_type = _CATEGORY_DOC_TYPES.get(category, "report")
  return SourceMeta(category=category, doc_type=doc_type)
