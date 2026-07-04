"""Apply graph/schema.cypher to Neo4j (one statement at a time, idempotent)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.graph.driver import close_driver, get_driver

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.cypher"


def _strip_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_cypher_statements(text: str) -> list[str]:
    """Split Cypher file into individual statements respecting braces."""
    cleaned = _strip_comments(text)
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    in_backtick = False

    for ch in cleaned:
        if ch == "`":
            in_backtick = not in_backtick
        elif not in_backtick:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)

        current.append(ch)
        if ch == ";" and depth == 0 and not in_backtick:
            stmt = "".join(current).strip()
            if stmt and stmt != ";":
                statements.append(stmt.rstrip(";").strip())
            current = []

    tail = "".join(current).strip()
    if tail:
        statements.append(tail.rstrip(";").strip())
    return statements


def apply_schema(*, dry_run: bool = False) -> int:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = split_cypher_statements(text)
    logger.info("Found %d statements in %s", len(statements), SCHEMA_PATH.name)

    if dry_run:
        for i, stmt in enumerate(statements, 1):
            preview = stmt.replace("\n", " ")[:120]
            print(f"{i}. {preview}...")
        return 0

    driver = get_driver()
    applied = 0
    try:
        with driver.session() as session:
            for i, stmt in enumerate(statements, 1):
                logger.info("Applying statement %d/%d", i, len(statements))
                session.run(stmt).consume()
                applied += 1
    finally:
        close_driver()

    logger.info("Applied %d statements", applied)
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply Neo4j schema from schema.cypher")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        apply_schema(dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Schema apply failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
