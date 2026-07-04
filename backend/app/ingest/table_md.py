"""Конвертация табличных строк в markdown (общая для DOCX и PPTX)."""

from __future__ import annotations


def dedup_row_cells(cells: list[str]) -> list[str]:
  if not cells:
    return cells
  result = [cells[0]]
  for cell in cells[1:]:
    if cell != result[-1]:
      result.append(cell)
  return result


def _is_header_row_cells(texts: list[str]) -> bool:
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


def rows_to_markdown(parsed_rows: list[list[str]]) -> str:
  if not parsed_rows:
    return ""

  header: list[str] | None = None
  data_rows = parsed_rows

  if (
    len(parsed_rows) >= 2
    and _is_header_row_cells(parsed_rows[0])
    and _is_header_row_cells(parsed_rows[1])
  ):
    header = _merge_header_rows(parsed_rows[0], parsed_rows[1])
    data_rows = parsed_rows[2:]
  elif len(parsed_rows) >= 1 and _is_header_row_cells(parsed_rows[0]):
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
