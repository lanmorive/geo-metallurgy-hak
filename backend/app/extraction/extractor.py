"""LLM-извлечение сущностей и связей с валидацией Pydantic."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.extraction.prompts import EXTRACTION_SYSTEM
from app.llm import LLMClient, get_llm_client
from app.schemas.ontology import (
    ExtractionResult,
    ExtractedEntity,
    ExtractedRelation,
    NumericConstraint,
    ParsedChunk,
    RelationType,
)

logger = logging.getLogger(__name__)

_MAX_VALIDATION_ATTEMPTS = 3
_NUMERIC_RELATION_TYPES = frozenset(
    {RelationType.HAS_PROPERTY, RelationType.OPERATES_AT_CONDITION}
)

def strip_json_fence(raw: str) -> str:
    """Снять markdown-обёртку ```json ... ``` если есть."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def parse_comma_float(value: Any) -> float | None:
    """Преобразовать строку с запятой в float; unit не трогаем."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "")
        if not cleaned:
            return None
        cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def coerce_numeric_strings(data: Any) -> Any:
    """Рекурсивно привести value/value_min/value_max в numeric-блоках."""
    if isinstance(data, dict):
        out = {k: coerce_numeric_strings(v) for k, v in data.items()}
        if "parameter" in out and "operator" in out and "unit" in out:
            for key in ("value", "value_min", "value_max"):
                if key in out:
                    coerced = parse_comma_float(out[key])
                    if coerced is not None or out[key] is None:
                        out[key] = coerced
        return out
    if isinstance(data, list):
        return [coerce_numeric_strings(item) for item in data]
    return data


def _coerce_numeric_constraint(nc: NumericConstraint | None) -> NumericConstraint | None:
    if nc is None:
        return None
    updates: dict[str, Any] = {}
    for key in ("value", "value_min", "value_max"):
        raw = getattr(nc, key)
        if isinstance(raw, str):
            parsed = parse_comma_float(raw)
            if parsed is not None:
                updates[key] = parsed
    if updates:
        return nc.model_copy(update=updates)
    return nc


def postvalidate(result: ExtractionResult) -> ExtractionResult:
    """Локальные постпроверки без повторного вызова LLM."""
    entities: list[ExtractedEntity] = []
    for entity in result.entities:
        if len(entity.name_norm.strip()) < 2:
            logger.warning(
                "Dropped entity with short name_norm: tmp_id=%s name_norm=%r",
                entity.tmp_id,
                entity.name_norm,
            )
            continue
        entities.append(entity)

    valid_ids = {e.tmp_id for e in entities}
    valid_refs = valid_ids | {"DOC"}

    relations: list[ExtractedRelation] = []
    for rel in result.relations:
        if rel.source not in valid_refs or rel.target not in valid_refs:
            logger.warning(
                "Dropped broken relation: %s -> %s (type=%s)",
                rel.source,
                rel.target,
                rel.type,
            )
            continue
        numeric = rel.numeric
        if numeric is not None and rel.type not in _NUMERIC_RELATION_TYPES:
            numeric = None
        elif numeric is not None:
            numeric = _coerce_numeric_constraint(numeric)
        relations.append(rel.model_copy(update={"numeric": numeric}))

    return ExtractionResult(entities=entities, relations=relations)


def _apply_retry_penalty(result: ExtractionResult) -> ExtractionResult:
    entities = [
        e.model_copy(update={"confidence": max(0.0, min(1.0, e.confidence - 0.2))})
        for e in result.entities
    ]
    relations = [
        r.model_copy(update={"confidence": max(0.0, min(1.0, r.confidence - 0.2))})
        for r in result.relations
    ]
    return ExtractionResult(entities=entities, relations=relations)


def parse_extraction_json(raw: str) -> ExtractionResult:
    """Распарсить и валидировать JSON ответа LLM."""
    cleaned = strip_json_fence(raw)
    data: dict[str, Any] = json.loads(cleaned)
    data = coerce_numeric_strings(data)
    result = ExtractionResult.model_validate(data)
    return postvalidate(result)


_PLACEHOLDER_KEYS = (
    "file_name",
    "doc_type",
    "venue",
    "year",
    "author_hint",
    "section",
    "kind",
    "lang",
    "canonical_terms",
)


def _build_system_prompt(chunk: ParsedChunk, canonical_terms: list[str]) -> str:
    values = {
        "file_name": chunk.file_name or "",
        "doc_type": chunk.doc_type or "unknown",
        "venue": chunk.venue or "",
        "year": chunk.year if chunk.year is not None else "",
        "author_hint": chunk.author_hint or "",
        "section": chunk.section or "",
        "kind": chunk.kind,
        "lang": chunk.lang,
        "canonical_terms": ", ".join(canonical_terms) if canonical_terms else "",
    }
    prompt = EXTRACTION_SYSTEM
    for key in _PLACEHOLDER_KEYS:
        prompt = prompt.replace("{" + key + "}", str(values[key]))
    return prompt


async def extract_chunk(
    chunk: ParsedChunk,
    canonical_terms: list[str],
    *,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> tuple[ExtractionResult | None, int, dict[str, Any]]:
    """
    Извлечь сущности и связи из чанка через LLM.

    Returns:
        (result, retries, usage) или (None, retries, usage) при hard-fail.
    """
    llm_client = llm or get_llm_client()
    llm_model = model or llm_client.model
    system_prompt = _build_system_prompt(chunk, canonical_terms)

    user_content = chunk.text
    validation_error: str | None = None
    retries = 0

    for attempt in range(_MAX_VALIDATION_ATTEMPTS):
        raw = await llm_client.complete_json(
            system_prompt, user_content, temperature=0.0, model=llm_model
        )
        usage = llm_client.last_usage

        try:
            result = parse_extraction_json(raw)
            if attempt > 0:
                retries = attempt
                result = _apply_retry_penalty(result)
            return result, retries, usage
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            if attempt == _MAX_VALIDATION_ATTEMPTS - 1:
                logger.error(
                    "extract_chunk failed after %d attempts for %s: %s",
                    _MAX_VALIDATION_ATTEMPTS,
                    chunk.chunk_id,
                    exc,
                )
                return None, attempt, usage

            # Пустой результат — валидный успех, не ретраим
            try:
                cleaned = strip_json_fence(raw)
                data = json.loads(cleaned)
                if data.get("entities") == [] and data.get("relations") == []:
                    empty = postvalidate(ExtractionResult())
                    if attempt > 0:
                        retries = attempt
                    return empty, retries, usage
            except (json.JSONDecodeError, ValidationError):
                pass

            validation_error = str(exc)
            user_content = (
                f"{chunk.text}\n\n"
                f"[Ошибка валидации предыдущего ответа — исправь JSON: {validation_error}]"
            )
            logger.warning(
                "Validation error for %s (attempt %d): %s",
                chunk.chunk_id,
                attempt + 1,
                exc,
            )

    return None, _MAX_VALIDATION_ATTEMPTS, {}
