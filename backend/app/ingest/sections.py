"""Назначение секций документа и выделение списка литературы."""

from __future__ import annotations

import difflib

from app.ingest.types import Block

REFERENCES_HEADINGS = frozenset(
  {
    "список использованных источников",
    "список литературы",
    "references",
    "библиография",
  }
)


def _fuzzy_match_references(heading_text: str) -> bool:
  normalized = heading_text.strip().casefold()
  for ref in REFERENCES_HEADINGS:
    if normalized == ref:
      return True
    if difflib.SequenceMatcher(None, normalized, ref).ratio() >= 0.85:
      return True
  return False


def assign_sections(blocks: list[Block]) -> tuple[list[Block], list[str]]:
  """Назначить section каждому блоку; вернуть (blocks, reference_texts)."""
  current_section = "frontmatter"
  in_references = False
  reference_texts: list[str] = []
  seen_heading = False

  for block in blocks:
    if block.type == "heading":
      seen_heading = True
      if _fuzzy_match_references(block.text):
        in_references = True
        current_section = "references"
        block.section = "references"
        continue
      in_references = False
      current_section = block.text.strip() or "untitled"
      block.section = current_section
      continue

    if not seen_heading:
      block.section = "frontmatter"
    elif in_references:
      block.section = "references"
      reference_texts.append(block.text)
    else:
      block.section = current_section

  return blocks, reference_texts
