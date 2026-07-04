#!/usr/bin/env python3
"""Smoke-test LLM: curl chat/completions и проверка валидного JSON."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def main() -> int:
    base_url = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "local")
    model = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Отвечай только валидным JSON без markdown."},
            {
                "role": "user",
                "content": (
                    'Извлеки из фразы "сульфаты 300 мг/л" параметр и значение. '
                    'Формат: {"parameter":"...","value":...,"unit":"..."}'
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 256,
    }
    if os.environ.get("LLM_GUIDED_JSON", "").lower() in ("1", "true", "yes"):
        payload["response_format"] = {"type": "json_object"}

    url = f"{base_url}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.load(resp)
    except urllib.error.URLError as exc:
        print(f"LLM smoke failed: {exc}", file=sys.stderr)
        return 1

    content = body["choices"][0]["message"]["content"]
    print(content)
    parsed = json.loads(strip_json_fence(content))
    print("Valid JSON:", json.dumps(parsed, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
