# Архитектура и границы модулей

## Pipeline (данные текут слева направо)

```
data/raw (PDF/DOCX)
   │ ingest/parser.py + chunker.py
   ▼
data/parsed/*.jsonl            (ParsedChunk)
   │ extraction/extractor.py (LLM) + normalizer.py
   ▼
data/extracted/*.jsonl         (Entity, Relation, NumericConstraint)
   │ graph/loader.py (UNWIND-батчи)
   ▼
Neo4j (граф + fulltext + vector index)
   │
   ├─ retrieval/embedder.py     ── семантический поиск (bge-m3)
   ├─ retrieval/text2cypher.py  ── точные фильтры, числовые диапазоны
   └─ retrieval/hybrid.py       ── слияние RRF → RetrievedContext
   │
   ▼
synthesis/answerer.py + gaps.py  (LLM-обзор, противоречия, пробелы)
   │
   ▼
api/query.py → QueryResponse → frontend
```

## Контракты между модулями (schemas/ — единственный интерфейс)

| Контракт | Producer | Consumer |
|---|---|---|
| `ParsedChunk` | ingest | extraction |
| `Entity`, `Relation`, `NumericConstraint` | extraction | graph |
| `RetrievedContext` | retrieval | synthesis |
| `QueryRequest` / `QueryResponse` | api | frontend |

Модули общаются ТОЛЬКО через эти модели и JSONL/Neo4j.
Прямые импорты между модулями (кроме schemas и config) запрещены —
это позволяет 5 людям работать параллельно без конфликтов.

## Поток обработки запроса (POST /api/query)

1. `QueryRequest` → text2cypher извлекает жёсткие фильтры
   (гео, годы, числовые диапазоны) и строит Cypher (read-only whitelist)
2. Параллельно: эмбеддинг запроса → vector search по чанкам
3. hybrid.py: RRF-слияние двух списков → top-K узлов + их 1-hop окружение
4. answerer.py: LLM-синтез обзора; каждое утверждение с [doc_id];
   секции: консенсус / противоречия (по рёбрам contradicts) / выводы
5. gaps.py: для сущностей запроса ищем комбинации без Experiment-связей
6. Сбор `QueryResponse`: answer_markdown, citations, graph_subset
   (узлы+рёбра для визуализации), contradictions, knowledge_gaps,
   recommended_experts (эксперты с максимумом authored_by в top-K)

## Деградация (обязательна)
- Neo4j недоступен → /api/query отдаёт мок с warning-флагом
- LLM недоступен → retrieval-результаты без синтеза (сырые цитаты)
- Фронт без бэка → VITE_USE_MOCKS=1

## Масштабирование (для презентации, НЕ кодим)
- Extraction — горизонтально по документам (очередь)
- Neo4j → кластер / шардинг по доменам; онтология конфигурируема (JSON)
- Новый домен = новая онтология + few-shot примеры, код не меняется
