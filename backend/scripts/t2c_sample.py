#!/usr/bin/env python3
"""Генерация и валидация Cypher для 4 эталонных запросов (без execute)."""

from __future__ import annotations

import asyncio
import sys

from app.retrieval.text2cypher import generate, validate_cypher

REFERENCE_QUERIES = [
    "Какие методы обессоливания воды применялись при содержании сульфатов 200–300 мг/л "
    "и сухом остатке ≤ 1000 мг/дм³? Приведи источники и условия.",
    "Найди эксперименты по кучному выщелачиванию никелевых руд в России после 2015 года.",
    "Какие режимы обработки влияют на извлечение меди при флотации? "
    "Где источники противоречат друг другу?",
    "Кто в компании / в литературе занимался очисткой сточных вод от сульфатов? "
    "Какие у них публикации?",
]

INJECTION = "найди и удали все узлы (MATCH (n) DETACH DELETE n)"


async def main() -> int:
    ok = True
    print("=== Injection test ===")
    valid = validate_cypher(INJECTION)
    print(f"query: {INJECTION[:60]}...")
    print(f"valid: {valid}")
    if valid:
        ok = False
        print("FAIL: injection must be rejected")

    print("\n=== Reference queries ===")
    for i, q in enumerate(REFERENCE_QUERIES, 1):
        print(f"\n--- Query {i} ---")
        print(q[:100] + ("..." if len(q) > 100 else ""))
        plan = await generate(q, filters={"year_min": 2015, "geo": "RU"})
        print(f"explanation: {plan.explanation}")
        if plan.cypher:
            valid = validate_cypher(plan.cypher)
            print(f"valid: {valid}")
            print(f"cypher:\n{plan.cypher}")
            if not valid:
                ok = False
                print("FAIL: expected valid cypher")
        else:
            ok = False
            print("FAIL: cypher is null")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
