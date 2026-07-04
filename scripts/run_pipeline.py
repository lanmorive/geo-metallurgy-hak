#!/usr/bin/env python3
"""E2E pipeline: parse → extract → load одной командой."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Repo root data dir
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PARSED = REPO_ROOT / "data" / "parsed"
DATA_EXTRACTED = REPO_ROOT / "data" / "extracted"
DATA_ROOT = REPO_ROOT / "data"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def step_ingest() -> int:
    """Парсинг и чанкинг документов из S3 / data/raw/."""
    from app.ingest.run import main

    return main()


def step_extract() -> int:
    """Извлечение сущностей из data/parsed/."""
    from app.extraction.run_extraction import main

    return main()


def step_load(from_s3: bool = False) -> int:
    """Загрузка data/extracted/ в Neo4j."""
    from neo4j import GraphDatabase

    from app.config import settings
    from app.graph.loader import load_jsonl
    from app.storage import get_storage

    storage = get_storage()
    if from_s3 and storage.available:
        storage.sync_prefix_down("extracted/", DATA_EXTRACTED)

    extracted_files = list(DATA_EXTRACTED.glob("*.jsonl"))
    if not extracted_files:
        logger.warning("No extracted JSONL in %s", DATA_EXTRACTED)
        return 0

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        for path in extracted_files:
            logger.info("Loading %s", path.name)
            try:
                load_jsonl(path, driver)
            except NotImplementedError as exc:
                logger.warning("Load not implemented: %s", exc)
                return 0
    finally:
        driver.close()
    return 0


def step_push_s3() -> int:
    from app.storage import get_storage

    storage = get_storage()
    if not storage.available:
        logger.warning("S3 not available — nothing to push")
        return 0
    storage.push_data_dir(DATA_ROOT)
    return 0


def step_pull_s3() -> int:
    from app.storage import get_storage

    storage = get_storage()
    if not storage.available:
        logger.warning("S3 not available — nothing to pull")
        return 0
    storage.pull_data_dir(DATA_ROOT)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Научный клубок pipeline")
    parser.add_argument(
        "--step",
        choices=["all", "ingest", "extract", "load"],
        default="all",
    )
    parser.add_argument(
        "--push-s3",
        action="store_true",
        help="Upload local data/ to S3 and exit",
    )
    parser.add_argument(
        "--pull-s3",
        action="store_true",
        help="Download data/ from S3 and exit",
    )
    parser.add_argument(
        "--from-s3",
        action="store_true",
        help="Before load step, sync extracted/ from S3 to local data/",
    )
    args = parser.parse_args()

    if args.push_s3:
        return step_push_s3()
    if args.pull_s3:
        return step_pull_s3()

    steps = {
        "ingest": step_ingest,
        "extract": step_extract,
        "load": lambda: step_load(from_s3=args.from_s3),
    }

    if args.step == "all":
        for name, fn in steps.items():
            if name == "load":
                code = step_load(from_s3=args.from_s3)
            else:
                code = fn()
            if code != 0:
                return code
        return 0

    if args.step == "load":
        return step_load(from_s3=args.from_s3)
    return steps[args.step]()


if __name__ == "__main__":
    sys.exit(main())
