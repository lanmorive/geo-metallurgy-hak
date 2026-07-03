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
    """Парсинг и чанкинг документов из data/raw/."""
    from app.ingest.chunker import write_jsonl
    from app.ingest.parser import parse_document
    from app.storage import get_storage

    storage = get_storage()
    files = list(DATA_RAW.glob("*.pdf")) + list(DATA_RAW.glob("*.docx"))
    if not files:
        logger.warning("No PDF/DOCX files in %s — skipping ingest", DATA_RAW)
        return 0

    for path in files:
        logger.info("Ingesting %s", path.name)
        try:
            chunks = parse_document(path)
            doc_id = path.stem
            out_path = DATA_PARSED / f"{doc_id}.jsonl"
            write_jsonl(chunks, out_path)
            if storage.available:
                storage.upload_file(path, f"raw/{path.name}")
                storage.upload_file(out_path, f"parsed/{doc_id}.jsonl")
        except NotImplementedError as exc:
            logger.warning("Ingest not implemented: %s", exc)
            return 0
        except Exception as exc:
            logger.error("Failed to ingest %s: %s", path, exc)
            return 1
    return 0


def step_extract() -> int:
    """Извлечение сущностей из data/parsed/."""
    from openai import OpenAI

    from app.config import settings
    from app.extraction.extractor import extract_from_chunk
    from app.extraction.normalizer import normalize_entity
    from app.schemas.ontology import ExtractionResult, ParsedChunk
    from app.storage import get_storage

    storage = get_storage()
    parsed_files = list(DATA_PARSED.glob("*.jsonl"))
    if not parsed_files:
        logger.warning("No parsed JSONL in %s", DATA_PARSED)
        return 0

    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

    for path in parsed_files:
        logger.info("Extracting from %s", path.name)
        results: list[ExtractionResult] = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                chunk = ParsedChunk.model_validate_json(line.strip())
                try:
                    result = extract_from_chunk(chunk, client, settings.llm_model)
                    result.entities = [
                        normalize_entity(e) for e in result.entities
                    ]
                    results.append(result)
                except NotImplementedError as exc:
                    logger.warning("Extract not implemented: %s", exc)
                    return 0

        out_path = DATA_EXTRACTED / path.name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as out:
            for result in results:
                out.write(result.model_dump_json() + "\n")
        if storage.available:
            storage.upload_jsonl(results, f"extracted/{path.name}")
    return 0


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
