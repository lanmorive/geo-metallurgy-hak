"""Фильтр OCR-мусора и колонтитулов."""

from __future__ import annotations

import re

_ALNUM_RE = re.compile(r"[а-яА-Яa-zA-Z0-9]")
_WORD_RE = re.compile(r"\S+")


def is_noise(text: str, *, is_table_cell: bool = False) -> bool:
  stripped = text.strip()
  if not stripped:
    return True
  if len(stripped) < 15 and not is_table_cell:
    return True

  total = len(stripped)
  alnum_count = len(_ALNUM_RE.findall(stripped))
  if total > 0 and alnum_count / total < 0.55:
    return True

  words = _WORD_RE.findall(stripped)
  if not words:
    return True
  long_words = sum(1 for w in words if len(w) >= 3)
  if long_words / len(words) < 0.4:
    return True

  return False
