#!/usr/bin/env python3
"""Разовая пометка библиографических чанков в Neo4j (SET c.is_reference = true).

Перечанкинг и переэмбеддинг НЕ выполняются. Скрипт идемпотентен: повторный запуск
помечает 0 новых чанков.
"""

from __future__ import annotations

import logging
import re
import sys
from collections import Counter
from typing import Any

from app.graph.driver import close_driver, get_driver

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MARKERS = [
    "БИБЛИОГРАФИЧЕСКИЙ СПИСОК",
    "СПИСОК ЛИТЕРАТУРЫ",
    "СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ",
    "REFERENCES",
    "ЛИТЕРАТУРА:",
]

MARKER_HEAD_CHARS = 200
HEURISTIC_HEAD_CHARS = 800
NUMBERED_REF_MIN = 4
NUMBERED_REF = re.compile(r"\b\d{1,2}\.\s+[А-ЯA-Z][а-яa-z]+\s+[А-ЯA-Z]\.")

BATCH_SIZE = 500

_FETCH_CHUNKS = """
MATCH (c:Chunk)
RETURN c.chunk_id AS chunk_id, c.text AS text, coalesce(c.is_reference, false) AS is_reference
"""

_MARK_CHUNKS = """
UNWIND $ids AS id
MATCH (c:Chunk {chunk_id: id})
SET c.is_reference = true
RETURN count(c) AS cnt
"""


def _match_reason(text: str) -> str | None:
    """Вернуть причину пометки чанка как библиографии, либо None."""
    if not text:
        return None
    head_upper = text[:MARKER_HEAD_CHARS].upper()
    for marker in MARKERS:
        if marker in head_upper:
            return marker
    if len(NUMBERED_REF.findall(text[:HEURISTIC_HEAD_CHARS])) >= NUMBERED_REF_MIN:
        return "numbered-refs-heuristic"
    return None


def mark_reference_chunks() -> int:
    driver = get_driver()
    try:
        with driver.session() as session:
            rows = [dict(r) for r in session.run(_FETCH_CHUNKS)]

            to_mark: list[str] = []
            reason_counts: Counter[str] = Counter()
            already_marked = 0

            for row in rows:
                reason = _match_reason(row.get("text") or "")
                if reason is None:
                    continue
                reason_counts[reason] += 1
                if row.get("is_reference"):
                    already_marked += 1
                else:
                    to_mark.append(row["chunk_id"])

            newly_marked = 0
            for i in range(0, len(to_mark), BATCH_SIZE):
                batch = to_mark[i : i + BATCH_SIZE]
                record = session.run(_MARK_CHUNKS, ids=batch).single()
                newly_marked += record["cnt"] if record else 0
    finally:
        close_driver()

    print(f"Total chunks scanned: {len(rows)}")
    print(f"Matched as reference: {sum(reason_counts.values())}")
    print(f"Newly marked: {newly_marked}")
    print(f"Already marked (unchanged): {already_marked}")
    print("Breakdown by marker/heuristic:")
    for reason, cnt in reason_counts.most_common():
        print(f"  {reason}: {cnt}")

    return newly_marked


def main(_argv: list[str] | None = None) -> int:
    mark_reference_chunks()
    return 0


if __name__ == "__main__":
    sys.exit(main())
