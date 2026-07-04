"""Извлечение author_hint из имени файла и починка PDF metadata author."""

from __future__ import annotations

import re
import string

_DOKLAD_RE = re.compile(r"Доклад_(.+)\.(pdf|docx|pptx|potx)$", re.IGNORECASE)
_SURNAME_INITIALS_RE = re.compile(
  r"^([А-ЯЁ][а-яё]+ [А-ЯЁ]\.? ?[А-ЯЁ]\.?)[ _]"
)
_FIO_ANYWHERE_RE = re.compile(
  r"([А-ЯЁ][а-яё]{2,}) ([А-ЯЁ])\.\s?([А-ЯЁ])\.?"
)
_UNDERSCORE_INITIALS_RE = re.compile(
  r"([А-ЯЁ][а-яё]{2,})_([А-ЯЁ])_?([А-ЯЁ])"
)
_ENGLISH_NAME_RE = re.compile(r"^([A-Z][a-z]+_[A-Z][a-z]+)_")
_CYRILLIC_INITIALS_RE = re.compile(
  r"^([А-ЯЁ][а-яё]+)\s+([А-ЯЁ])\.?\s*([А-ЯЁ])\.?$"
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_NORMAL_CHARS = set(
  string.ascii_letters
  + string.digits
  + " .,;:!?-'\"()[]{}«»/\\@#&%+–—"
  + "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
)

_DECODE_CANDIDATES = ("cp1251", "cp866", "koi8-r", "utf-8")


def _letter_ratio(text: str) -> float:
  if not text:
    return 0.0
  letters = sum(1 for c in text if c.isalpha())
  return letters / len(text)


def _has_pdfdoc_garbage(text: str) -> bool:
  if _CONTROL_CHARS_RE.search(text):
    return True
  suspicious = sum(1 for c in text if c not in _NORMAL_CHARS and not c.isspace())
  if suspicious / max(len(text), 1) > 0.15:
    return True
  if any(c in text for c in "˜ˆ€‚ƒ„…†‡‰Š‹ŒŽ''""•"):
    return True
  if re.search(r"[=>0-9]{3,}", text):
    return True
  return False


def _try_decode_variants(raw: str) -> str | None:
  try:
    raw_bytes = raw.encode("latin-1")
  except UnicodeEncodeError:
    return None

  for encoding in _DECODE_CANDIDATES:
    try:
      decoded = raw_bytes.decode(encoding)
    except (UnicodeDecodeError, LookupError):
      continue
    if _CONTROL_CHARS_RE.search(decoded):
      continue
    if _letter_ratio(decoded) >= 0.5:
      return decoded.strip() or None
  return None


def fix_file_metadata_author(raw: str | None) -> str | None:
  """Починить или сохранить PDF/DOCX metadata author (только для отладки)."""
  if not raw or not raw.strip():
    return None
  stripped = raw.strip()
  if not _has_pdfdoc_garbage(stripped):
    return stripped
  return _try_decode_variants(stripped)


def _normalize_author_hint(hint: str) -> str:
  hint = hint.strip()
  match = _CYRILLIC_INITIALS_RE.match(hint)
  if match:
    surname, i1, i2 = match.groups()
    return f"{surname} {i1}.{i2}."
  return hint


def extract_author_hint(file_name: str) -> str | None:
  """Извлечь подсказку автора из имени файла."""
  match = _DOKLAD_RE.search(file_name)
  if match:
    return _normalize_author_hint(match.group(1).strip())

  match = _UNDERSCORE_INITIALS_RE.search(file_name)
  if match:
    surname, i1, i2 = match.groups()
    return f"{surname} {i1}.{i2}."

  match = _FIO_ANYWHERE_RE.search(file_name)
  if match:
    surname, i1, i2 = match.groups()
    return f"{surname} {i1}.{i2}."

  match = _SURNAME_INITIALS_RE.match(file_name)
  if match:
    return _normalize_author_hint(match.group(1).strip())

  match = _ENGLISH_NAME_RE.match(file_name)
  if match:
    return match.group(1).replace("_", " ")

  return None
