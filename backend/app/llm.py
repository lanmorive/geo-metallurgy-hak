"""Единый OpenAI-compatible LLM-клиент для extraction, synthesis и прочих вызовов."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 2.0
_BACKOFF_MAX = 60.0


class LLMClient:
    """OpenAI-compatible async client; провайдер задаётся base_url + api_key из конфига."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        guided_json: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.model = model
        self.guided_json = guided_json
        self._client = AsyncOpenAI(
            api_key=api_key or "local",
            base_url=self.base_url,
            timeout=timeout,
            max_retries=0,
        )
        self.last_usage: dict[str, int | None] = {}

    async def ensure_available(self, timeout: float = 8.0) -> None:
        """Проверить доступность LLM; fail-fast при недоступности."""
        url = f"{self.base_url}models"
        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                response = await http.get(
                    url,
                    headers={"Authorization": f"Bearer {self._client.api_key}"},
                )
                response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"LLM недоступен по {self.base_url}") from exc

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 4000,
        temperature: float = 0.2,
        *,
        model: str | None = None,
    ) -> str:
        """Chat completion (plain text/markdown) с transport-retry."""
        return await self._complete_impl(
            system,
            user,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            json_mode=False,
        )

    async def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        *,
        model: str | None = None,
    ) -> str:
        """Chat completion с опциональным guided JSON и transport-retry."""
        return await self._complete_impl(
            system,
            user,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            json_mode=True,
        )

    async def _complete_impl(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
        temperature: float,
        model: str | None,
        json_mode: bool,
    ) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        use_guided = json_mode and self.guided_json
        delay = _BACKOFF_BASE

        while True:
            try:
                kwargs: dict[str, Any] = {
                    "model": model or self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if use_guided:
                    kwargs["response_format"] = {"type": "json_object"}

                response = await self._client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Empty LLM response")

                self.last_usage = {}
                if response.usage:
                    self.last_usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                    }
                return content

            except APIStatusError as exc:
                if use_guided and _is_response_format_unsupported(exc):
                    logger.warning(
                        "response_format not supported, retrying without guided JSON"
                    )
                    use_guided = False
                    continue
                if exc.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "LLM HTTP %s, retry in %.1fs", exc.status_code, delay
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, _BACKOFF_MAX)
                    continue
                raise

            except APITimeoutError:
                logger.warning("LLM timeout, retry in %.1fs", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, _BACKOFF_MAX)
                continue

            except APIConnectionError as exc:
                raise RuntimeError(f"LLM недоступен по {self.base_url}") from exc


def _is_response_format_unsupported(exc: APIStatusError) -> bool:
    message = str(exc.message).lower()
    return "response_format" in message or "not supported" in message


_client: LLMClient | None = None
_synthesis_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Singleton LLMClient из settings."""
    global _client
    if _client is None:
        _client = LLMClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout=float(settings.llm_timeout),
            guided_json=settings.llm_guided_json,
        )
    return _client


def get_synthesis_client() -> LLMClient:
    """LLMClient для synthesis с fallback на основные llm_* настройки."""
    global _synthesis_client
    if _synthesis_client is None:
        _synthesis_client = LLMClient(
            api_key=settings.llm_api_key,
            base_url=settings.effective_synthesis_base_url,
            model=settings.effective_synthesis_model,
            timeout=float(settings.llm_timeout),
            guided_json=False,
        )
    return _synthesis_client
