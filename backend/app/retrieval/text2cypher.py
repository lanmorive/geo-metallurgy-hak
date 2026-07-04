"""LLM → Cypher с whitelist-валидацией (только чтение)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from neo4j import READ_ACCESS
from pydantic import BaseModel

from app.extraction.extractor import strip_json_fence
from app.graph.driver import get_driver
from app.llm import get_llm_client
from app.synthesis.prompts import TEXT2CYPHER_SYSTEM

logger = logging.getLogger(__name__)

CYPHER_BLACKLIST = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL|LOAD|FOREACH|apoc\.)\b",
    re.IGNORECASE,
)
CYPHER_MUST_START_MATCH = re.compile(r"^\s*MATCH\b", re.IGNORECASE | re.DOTALL)
UNBOUNDED_PATH = re.compile(r"\[\*\]|\[\*\.\.\]", re.IGNORECASE)
LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


class CypherPlan(BaseModel):
    cypher: str | None
    explanation: str


def _validation_error(cypher: str) -> str | None:
    if CYPHER_BLACKLIST.search(cypher):
        return "запрещённые операции (CREATE/MERGE/DELETE/CALL/apoc/...)"
    if not CYPHER_MUST_START_MATCH.match(cypher.strip()):
        return "запрос должен начинаться с MATCH"
    if UNBOUNDED_PATH.search(cypher):
        return "переменная длина пути без верхней границы ([*] или [*..])"
    return None


def normalize_cypher_limit(cypher: str) -> str:
    """Дописать или заменить LIMIT на 50 если отсутствует или > 100."""
    match = LIMIT_PATTERN.search(cypher)
    if match is None:
        stripped = cypher.rstrip().rstrip(";")
        return f"{stripped}\nLIMIT 50"
    limit_val = int(match.group(1))
    if limit_val > 100:
        return LIMIT_PATTERN.sub("LIMIT 50", cypher, count=1)
    return cypher


def normalize_cypher(cypher: str) -> str | None:
    """Валидировать и нормализовать LIMIT; None если reject."""
    reason = _validation_error(cypher)
    if reason:
        return None
    return normalize_cypher_limit(cypher)


def validate_cypher(cypher: str) -> bool:
    """Проверить, что Cypher-запрос безопасен (read-only whitelist)."""
    return normalize_cypher(cypher) is not None


def _format_filters(filters: dict[str, Any] | None) -> str:
    if not filters:
        return ""
    lines: list[str] = ["\n\nДополнительные фильтры контекста:"]
    if filters.get("year_min") is not None or filters.get("year_max") is not None:
        lines.append(
            f"- Годы: {filters.get('year_min', '…')}–{filters.get('year_max', '…')}"
        )
    if filters.get("geo"):
        lines.append(f"- География: {filters['geo']}")
    if filters.get("min_confidence") is not None:
        lines.append(f"- Мин. confidence: {filters['min_confidence']}")
    numeric = filters.get("numeric_filters") or []
    for nf in numeric:
        if isinstance(nf, dict):
            lines.append(f"- Числовой фильтр: {nf}")
        else:
            lines.append(f"- Числовой фильтр: {nf.model_dump() if hasattr(nf, 'model_dump') else nf}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _parse_plan(raw: str) -> CypherPlan:
    cleaned = strip_json_fence(raw)
    data = json.loads(cleaned)
    return CypherPlan(
        cypher=data.get("cypher"),
        explanation=str(data.get("explanation") or ""),
    )


async def generate(query: str, filters: dict[str, Any] | None = None) -> CypherPlan:
    """Сгенерировать Cypher из естественного языка через LLM."""
    llm = get_llm_client()
    user = query + _format_filters(filters)
    last_reason = "не удалось сгенерировать валидный Cypher"

    for attempt in range(2):
        try:
            raw = await llm.complete_json(
                TEXT2CYPHER_SYSTEM,
                user,
                temperature=0.0,
                max_tokens=2000,
            )
            plan = _parse_plan(raw)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("text2cypher JSON parse error: %s", exc)
            last_reason = f"невалидный JSON от LLM: {exc}"
            if attempt == 0:
                user = f"Ошибка валидации: {last_reason}\nИсходный запрос: {query}"
                continue
            return CypherPlan(cypher=None, explanation=last_reason)

        if plan.cypher is None:
            return plan

        normalized = normalize_cypher(plan.cypher)
        if normalized is not None:
            return CypherPlan(cypher=normalized, explanation=plan.explanation)

        last_reason = _validation_error(plan.cypher) or "не прошёл whitelist"
        logger.warning("text2cypher validation failed (attempt %d): %s", attempt + 1, last_reason)
        if attempt == 0:
            user = (
                f"Ошибка валидации: {last_reason}\n"
                f"Исходный запрос: {query}\n"
                f"Невалидный Cypher: {plan.cypher[:500]}"
            )

    return CypherPlan(cypher=None, explanation=last_reason)


async def execute(plan: CypherPlan) -> list[dict[str, Any]]:
    """Исполнить read-only Cypher; при ошибке — пустой список."""
    if not plan.cypher:
        return []
    driver = get_driver()
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            result = session.run(plan.cypher, timeout=10.0)
            return [dict(record) for record in result]
    except Exception as exc:
        logger.exception("text2cypher execute failed: %s", exc)
        return []


async def retrieve_graph(query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """generate → execute pipeline."""
    plan = await generate(query, filters)
    if not plan.cypher:
        logger.info("text2cypher: no cypher (%s)", plan.explanation)
        return []
    rows = await execute(plan)
    logger.info("text2cypher: %d rows", len(rows))
    return rows
