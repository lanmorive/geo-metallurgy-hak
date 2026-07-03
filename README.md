# Научный клубок

Поисково-аналитическая система на базе графа знаний для R&D-документов горно-металлургической отрасли. Хакатон Норникель AI Science Hack, трек 2.

## Архитектура (6 блоков)

```
data/raw (PDF/DOCX)
   │ ① ingest/     — парсинг, чанкинг
   ▼
data/parsed/*.jsonl
   │ ② extraction/ — LLM: сущности, связи, числа
   ▼
data/extracted/*.jsonl
   │ ③ graph/      — Neo4j: загрузка, индексы
   ▼
Neo4j (fulltext + vector)
   │ ④ retrieval/  — bge-m3 + text2cypher → hybrid RRF
   ▼
   │ ⑤ synthesis/  — обзор, противоречия, пробелы
   ▼
   │ ⑥ api/ + frontend — чат, граф, фильтры, экспорт MD
```

Контракты между модулями — **только** через `backend/app/schemas/`. Модули не импортируют друг друга напрямую.

## Быстрый старт (3 команды)

```bash
cp .env.example .env
make up
# Открыть http://localhost:5173
```

Локальная разработка без Docker:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload --port 8000

cd frontend && npm install && npm run dev
```

## Распределение модулей

| Модуль | Владелец | Зависит от |
|--------|----------|------------|
| `ingest/` + data-prep | Mid 2 | — |
| `extraction/` | Senior 2 | schemas, `data/parsed/` |
| `graph/` | Senior 1 | schemas, `data/extracted/` |
| `retrieval/` | Senior 1 | graph (Neo4j) |
| `synthesis/` + `api/` | Strong | schemas (моки до retrieval) |
| `frontend/` | Mid 1 | `schemas/api.py` |
| Презентация, сабмит | Mid 2 | демо от всех |

**Ч+2: контракты `schemas/` заморожены.** Изменение — только с согласия всей команды.

## Makefile

| Цель | Описание |
|------|----------|
| `make up` | docker compose up (Neo4j + backend + frontend) |
| `make down` | Остановить контейнеры |
| `make ingest` | Парсинг `data/raw/` → `data/parsed/` |
| `make extract` | LLM-извлечение → `data/extracted/` |
| `make load-graph` | Загрузка JSONL в Neo4j |
| `make test` | E2E на 4 эталонных запросах |
| `make seed-demo` | Мини-граф ~20 узлов для демо |

## API

- `GET /api/health` — статус сервиса и Neo4j
- `POST /api/query` — главный эндпоинт (сейчас мок `QueryResponse`)
- `GET /api/graph/subgraph` — подграф для визуализации

Фронт работает на `frontend/src/mocks/response.json` при `VITE_USE_MOCKS=1`.

## Документация

Подробности в [`cursor-docs/docs/`](cursor-docs/docs/):

- [ONTOLOGY.md](cursor-docs/docs/ONTOLOGY.md) — типы сущностей и связей
- [ARCHITECTURE.md](cursor-docs/docs/ARCHITECTURE.md) — границы модулей
- [TEAM.md](cursor-docs/docs/TEAM.md) — таймлайн 24ч
- [DEMO.md](cursor-docs/docs/DEMO.md) — эталонные запросы жюри

## Стек

- Backend: Python 3.11, FastAPI, Pydantic v2, Neo4j 5 (APOC + GDS)
- Embeddings: bge-m3 (sentence-transformers)
- Frontend: Vite, React, TypeScript, Tailwind, react-force-graph-2d
