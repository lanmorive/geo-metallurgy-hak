"""LLM-синтез обзора с цитатами, консенсусом и противоречиями."""

from __future__ import annotations

import logging

from app.config import settings
from app.llm import LLMClient, get_llm_client
from app.schemas.api import Citation, RetrievedContext

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """Ты — аналитик R&D литературы горно-металлургической отрасли.
Сформируй структурированный обзор по контексту из графа знаний.
Каждое утверждение сопровождай ссылкой [doc_id].
Выдели секции: консенсус, противоречия, выводы.
Температура 0.2. Ответ — markdown."""


def synthesize_answer(
    query: str,
    context: RetrievedContext,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> tuple[str, list[Citation]]:
    """
    Синтезировать markdown-ответ с цитатами из RetrievedContext.

    Args:
        query: Запрос пользователя.
        context: Контекст из hybrid retrieval.
        llm: OpenAI-compatible LLM-клиент.
        model: Имя модели (default — settings.llm_model).

    Returns:
        Кортеж (answer_markdown, citations).

    Raises:
        NotImplementedError: Реализация — владелец Strong.
    """
    _ = llm or get_llm_client()
    _ = model or settings.llm_model
    logger.info("synthesize_answer query=%r", query[:80])
    raise NotImplementedError(
        "synthesize_answer: LLM synthesis with [doc_id] citations"
    )
