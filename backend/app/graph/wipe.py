"""Полная очистка графа Neo4j (nodes + relationships). Эмбеддинги на диске не трогает."""

from __future__ import annotations

import logging
import sys

from app.graph.driver import close_driver, get_driver

logger = logging.getLogger(__name__)

_WIPE_BATCH = """
MATCH (n)
CALL (n) {
  DETACH DELETE n
} IN TRANSACTIONS OF 10000 ROWS
"""

_COUNT = "MATCH (n) RETURN count(n) AS cnt"


def wipe_graph() -> int:
    """Удалить все узлы и связи. Возвращает число узлов до очистки."""
    driver = get_driver()
    try:
        with driver.session() as session:
            before = session.run(_COUNT).single()
            n_before = before["cnt"] if before else 0
            session.run(_WIPE_BATCH).consume()
            after = session.run(_COUNT).single()
            n_after = after["cnt"] if after else 0
        logger.info("Graph wiped: %d nodes deleted (%d remaining)", n_before - n_after, n_after)
        return n_before
    finally:
        close_driver()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    wipe_graph()
    return 0


if __name__ == "__main__":
    sys.exit(main())
