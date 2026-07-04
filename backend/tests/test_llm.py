"""Unit tests for LLMClient (no live LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.llm import LLMClient, _is_response_format_unsupported, get_llm_client


def _make_client(**kwargs) -> LLMClient:
    defaults = {
        "api_key": "test-key",
        "base_url": "http://llm.test/v1/",
        "model": "test-model",
        "timeout": 30.0,
        "guided_json": False,
    }
    defaults.update(kwargs)
    return LLMClient(**defaults)


def _mock_response(content: str = '{"ok":true}', prompt: int = 10, completion: int = 5):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    response.usage = MagicMock(prompt_tokens=prompt, completion_tokens=completion)
    return response


def test_complete_json_happy_path() -> None:
    async def run() -> None:
        client = _make_client()
        client._client.chat.completions.create = AsyncMock(return_value=_mock_response())

        result = await client.complete_json("sys", "user")

        assert result == '{"ok":true}'
        assert client.last_usage == {"prompt_tokens": 10, "completion_tokens": 5}
        client._client.chat.completions.create.assert_awaited_once()
        call_kwargs = client._client.chat.completions.create.await_args.kwargs
        assert "response_format" not in call_kwargs

    anyio.run(run)


def test_complete_json_guided_json() -> None:
    async def run() -> None:
        client = _make_client(guided_json=True)
        client._client.chat.completions.create = AsyncMock(return_value=_mock_response())

        await client.complete_json("sys", "user")

        call_kwargs = client._client.chat.completions.create.await_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}

    anyio.run(run)


def test_complete_json_guided_fallback() -> None:
    async def run() -> None:
        client = _make_client(guided_json=True)
        err = APIStatusError(
            message="response_format not supported",
            response=MagicMock(status_code=400),
            body=None,
        )
        client._client.chat.completions.create = AsyncMock(
            side_effect=[err, _mock_response('{"parameter":"сульфаты","value":300}')]
        )

        result = await client.complete_json("sys", "user")

        assert "сульфаты" in result
        assert client._client.chat.completions.create.await_count == 2
        second_call = client._client.chat.completions.create.await_args_list[1].kwargs
        assert "response_format" not in second_call

    anyio.run(run)


def test_complete_json_connection_error_fail_fast() -> None:
    async def run() -> None:
        client = _make_client()
        client._client.chat.completions.create = AsyncMock(
            side_effect=APIConnectionError(request=MagicMock())
        )

        with pytest.raises(RuntimeError, match="LLM недоступен по"):
            await client.complete_json("sys", "user")

    anyio.run(run)


def test_complete_json_retries_on_429() -> None:
    async def run() -> None:
        client = _make_client()
        err = APIStatusError(
            message="rate limit",
            response=MagicMock(status_code=429),
            body=None,
        )
        client._client.chat.completions.create = AsyncMock(
            side_effect=[err, _mock_response()]
        )

        with patch("app.llm.asyncio.sleep", new_callable=AsyncMock):
            result = await client.complete_json("sys", "user")

        assert result == '{"ok":true}'
        assert client._client.chat.completions.create.await_count == 2

    anyio.run(run)


def test_complete_json_retries_on_timeout() -> None:
    async def run() -> None:
        client = _make_client()
        client._client.chat.completions.create = AsyncMock(
            side_effect=[APITimeoutError(request=MagicMock()), _mock_response()]
        )

        with patch("app.llm.asyncio.sleep", new_callable=AsyncMock):
            result = await client.complete_json("sys", "user")

        assert result == '{"ok":true}'

    anyio.run(run)


def test_ensure_available_ok() -> None:
    async def run() -> None:
        client = _make_client()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch("app.llm.httpx.AsyncClient", return_value=mock_http):
            await client.ensure_available()

        mock_http.get.assert_awaited_once()

    anyio.run(run)


def test_ensure_available_raises() -> None:
    async def run() -> None:
        client = _make_client()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch("app.llm.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(RuntimeError, match="LLM недоступен по"):
                await client.ensure_available()

    anyio.run(run)


def test_is_response_format_unsupported() -> None:
    exc = APIStatusError(
        message="response_format not supported by this model",
        response=MagicMock(status_code=400),
        body=None,
    )
    assert _is_response_format_unsupported(exc) is True


def test_get_llm_client_singleton() -> None:
    import app.llm as llm_module

    llm_module._client = None
    with patch("app.llm.settings") as mock_settings:
        mock_settings.llm_api_key = "test-key"
        mock_settings.llm_base_url = "http://llm.test/v1/"
        mock_settings.llm_model = "test-model"
        mock_settings.llm_timeout = 30
        mock_settings.llm_guided_json = False
        c1 = get_llm_client()
        c2 = get_llm_client()
        assert c1 is c2
    llm_module._client = None
