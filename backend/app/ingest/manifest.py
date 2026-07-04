"""Манифест обработанных файлов ingest."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_NAME = "_manifest.json"


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
  if not path.exists():
    return {}
  try:
    with path.open(encoding="utf-8") as f:
      data = json.load(f)
    if isinstance(data, dict):
      return data
  except (json.JSONDecodeError, OSError) as exc:
    logger.warning("Could not load manifest %s: %s", path, exc)
  return {}


def save_manifest(path: Path, manifest: dict[str, dict[str, Any]]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_suffix(".json.tmp")
  with tmp.open("w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
  tmp.replace(path)
  logger.debug("Manifest flushed: %d entries", len(manifest))
