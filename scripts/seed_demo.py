#!/usr/bin/env python3
"""Загрузка мини-графа (~20 узлов) для мгновенного демо."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "extracted" / "demo_seed.jsonl"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_demo_extraction() -> dict:
    """Собрать ExtractionResult для темы обессоливания / сульфаты."""
    from app.schemas.ontology import (
        DocType,
        Entity,
        EntityType,
        GraphExtractionBundle,
        ExperimentScale,
        Lang,
        NumericConstraint,
        NumericOperator,
        OrgType,
        Relation,
        RelationType,
        VerificationMeta,
    )

    def vm(doc: str, conf: float, geo: str = "RU", year: int = 2019) -> VerificationMeta:
        return VerificationMeta(source_doc=doc, confidence=conf, geography=geo, year=year)

    ids = {k: str(uuid.uuid4()) for k in [
        "ro", "ie", "water", "sulfate", "tds",
        "exp1", "exp2", "exp3", "pub1", "pub2", "pub3",
        "expert1", "expert2", "fac1", "equip1", "org1",
        "prop_temp", "prop_pressure",
    ]}

    entities = [
        Entity(type=EntityType.PROCESS, name="обратный осмос", name_norm="обратный осмос",
               category="мембранный", verification=vm("demo", 0.9)),
        Entity(type=EntityType.PROCESS, name="ионный обмен", name_norm="ионный обмен",
               category="реагентный", verification=vm("demo", 0.88)),
        Entity(type=EntityType.MATERIAL, name="техническая вода", name_norm="техническая вода",
               verification=vm("demo", 0.85)),
        Entity(type=EntityType.PROPERTY, name="сульфаты", name_norm="сульфаты",
               unit="мг/л", verification=vm("demo", 0.95)),
        Entity(type=EntityType.PROPERTY, name="сухой остаток", name_norm="сухой остаток",
               unit="мг/дм³", verification=vm("demo", 0.95)),
        Entity(type=EntityType.PROPERTY, name="температура", name_norm="температура",
               unit="°C", verification=vm("demo", 0.9)),
        Entity(type=EntityType.EXPERIMENT, name="Пилот RO при 250 мг/л SO4", name_norm="пилот ro 250",
               scale=ExperimentScale.PILOT, verification=vm("pub-001", 0.92, year=2019)),
        Entity(type=EntityType.EXPERIMENT, name="Ионообмен 280 мг/л", name_norm="ионообмен 280",
               scale=ExperimentScale.LAB, verification=vm("pub-002", 0.88, year=2021)),
        Entity(type=EntityType.EXPERIMENT, name="RO bench 220 мг/л", name_norm="ro bench 220",
               scale=ExperimentScale.LAB, verification=vm("pub-003", 0.86, "WORLD", 2020)),
        Entity(type=EntityType.PUBLICATION, name="Обессоливание шахтных вод ЗФ", name_norm="обессоливание зф",
               year=2019, lang=Lang.RU, doc_type=DocType.REPORT,
               venue="Отчёт НИЦ водоподготовки", source_path="data/corpus/pub-001.pdf",
               verification=vm("pub-001", 0.95)),
        Entity(type=EntityType.PUBLICATION, name="Mine water desalination review", name_norm="desalination review",
               year=2020, lang=Lang.EN, doc_type=DocType.ARTICLE,
               venue="Mine Water and the Environment", source_path="data/corpus/pub-002.pdf",
               verification=vm("pub-002", 0.9, "WORLD")),
        Entity(type=EntityType.PUBLICATION, name="Membrane limits for sulfate removal", name_norm="membrane sulfate",
               year=2018, lang=Lang.EN, doc_type=DocType.ARTICLE,
               source_path="data/corpus/pub-003.pdf",
               verification=vm("pub-003", 0.87, "WORLD")),
        Entity(type=EntityType.EXPERT, name="Иванов А.С.", name_norm="иванов а.с.",
               affiliation="НИЦ водоподготовки", verification=vm("pub-001", 0.9)),
        Entity(type=EntityType.EXPERT, name="Smith J.", name_norm="smith j.",
               affiliation="Mining Water Research", verification=vm("pub-002", 0.85, "WORLD")),
        Entity(type=EntityType.ORGANIZATION, name="ЗФ Норникель", name_norm="зф норникель",
               org_type=OrgType.COMPANY, country="RU", verification=vm("pub-001", 0.9)),
        Entity(type=EntityType.FACILITY, name="Пилотная установка ЗФ", name_norm="пилот зф",
               location="RU", verification=vm("pub-001", 0.9)),
        Entity(type=EntityType.EQUIPMENT, name="Мембранный модуль RO-400", name_norm="ro-400",
               model="RO-400", verification=vm("pub-001", 0.88)),
    ]

    key_map = ["ro", "ie", "water", "sulfate", "tds", "prop_temp", "exp1", "exp2", "exp3",
               "pub1", "pub2", "pub3", "expert1", "expert2", "org1", "fac1", "equip1"]
    for entity, key in zip(entities, key_map):
        entity.id = ids[key]

    nc_sulfate = NumericConstraint(
        parameter="сульфаты", operator=NumericOperator.LTE, value=300.0, unit="мг/л"
    )
    nc_tds = NumericConstraint(
        parameter="сухой остаток", operator=NumericOperator.LTE, value=1000.0, unit="мг/дм³"
    )

    relations = [
        Relation(type=RelationType.VALIDATED_BY, source_id=ids["exp1"], target_id=ids["ro"],
                 verification=vm("pub-001", 0.92)),
        Relation(type=RelationType.OPERATES_AT_CONDITION, source_id=ids["exp1"], target_id=ids["sulfate"],
                 numeric_constraints=[nc_sulfate], verification=vm("pub-001", 0.92)),
        Relation(type=RelationType.OPERATES_AT_CONDITION, source_id=ids["exp1"], target_id=ids["tds"],
                 numeric_constraints=[nc_tds], verification=vm("pub-001", 0.92)),
        Relation(type=RelationType.DESCRIBED_IN, source_id=ids["exp1"], target_id=ids["pub1"],
                 verification=vm("pub-001", 0.95)),
        Relation(type=RelationType.USES_MATERIAL, source_id=ids["exp1"], target_id=ids["water"],
                 verification=vm("pub-001", 0.9)),
        Relation(type=RelationType.USES_EQUIPMENT, source_id=ids["exp1"], target_id=ids["equip1"],
                 verification=vm("pub-001", 0.88)),
        Relation(type=RelationType.CONDUCTED_AT, source_id=ids["exp1"], target_id=ids["fac1"],
                 verification=vm("pub-001", 0.9)),
        Relation(type=RelationType.AUTHORED_BY, source_id=ids["pub1"], target_id=ids["expert1"],
                 verification=vm("pub-001", 0.95)),
        Relation(type=RelationType.AFFILIATED_WITH, source_id=ids["expert1"], target_id=ids["org1"],
                 verification=vm("pub-001", 0.9)),
        Relation(type=RelationType.OWNS, source_id=ids["org1"], target_id=ids["fac1"],
                 date_from="2015", verification=vm("pub-001", 0.88)),
        Relation(type=RelationType.OPERATES, source_id=ids["org1"], target_id=ids["fac1"],
                 date_from="2016", verification=vm("pub-001", 0.88)),
        Relation(type=RelationType.VALIDATED_BY, source_id=ids["exp2"], target_id=ids["ie"],
                 verification=vm("pub-002", 0.88)),
        Relation(type=RelationType.DESCRIBED_IN, source_id=ids["exp2"], target_id=ids["pub2"],
                 verification=vm("pub-002", 0.9)),
        Relation(type=RelationType.AUTHORED_BY, source_id=ids["pub2"], target_id=ids["expert2"],
                 verification=vm("pub-002", 0.85)),
        Relation(type=RelationType.CONTRADICTS, source_id=ids["pub1"], target_id=ids["pub2"],
                 verification=vm("demo", 0.8)),
        Relation(type=RelationType.DESCRIBED_IN, source_id=ids["exp3"], target_id=ids["pub3"],
                 verification=vm("pub-003", 0.87)),
        Relation(type=RelationType.VALIDATED_BY, source_id=ids["exp3"], target_id=ids["ro"],
                 verification=vm("pub-003", 0.86)),
    ]

    result = GraphExtractionBundle(doc_id="demo_seed", entities=entities, relations=relations)
    return result.model_dump(mode="json")


def main() -> int:
    data = build_demo_extraction()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
    logger.info("Wrote demo seed to %s (%d entities)", OUT_PATH, len(data["entities"]))

    try:
        from neo4j import GraphDatabase

        from app.config import settings
        from app.graph.loader import load_jsonl

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        try:
            logger.warning(
                "demo_seed uses legacy GraphExtractionBundle format — "
                "run extraction or use _sample.jsonl for graph load"
            )
        finally:
            driver.close()
    except Exception as exc:
        logger.warning("Neo4j load skipped: %s", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
