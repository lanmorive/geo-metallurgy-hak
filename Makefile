.PHONY: up down init-db embed-only ingest extract extract-core extract-sample load-chunks load-graph load-graph-sample graph-wipe graph-reset graph-report dedup dedup-export dedup-offline dedup-filter dedup-apply test seed-demo s3-push s3-pull s3-push-embeddings s3-pull-embeddings s3-push-extracted s3-pull-extracted llm-up llm-smoke t2c-sample synth-sample ref-queries mark-reference-chunks

DRY_RUN ?= 1
INPUT ?= data/dedup_entities.json
PLAN ?= data/dedup_plan.json
FILTERED_PLAN ?= data/dedup_plan_filtered.json
EMBED_DEVICE ?= cuda
PYTHON ?= python3

# .env задаёт bolt://neo4j:7687 для Docker; при make с хоста — localhost (порт 7687 проброшен).
define run_with_host_neo4j
set -a && [ -f .env ] && . ./.env; set +a; \
case "$$NEO4J_URI" in bolt://neo4j:7687) export NEO4J_URI=bolt://localhost:7687 ;; esac;
endef

up:
	docker compose up -d --build

down:
	docker compose down

test:
	cd backend && .venv/bin/python -m pytest tests/test_e2e.py -v

seed-demo:
	PYTHONPATH=backend backend/.venv/bin/python scripts/seed_demo.py

ingest:
	PYTHONPATH=backend backend/.venv/bin/python -m app.ingest.run $(if $(FORCE),--force,)

extract:
	PYTHONPATH=backend backend/.venv/bin/python -m app.extraction.run_extraction $(if $(FORCE),--force,)

extract-core:
	PYTHONPATH=backend backend/.venv/bin/python -m app.extraction.run_extraction --core-only $(if $(FORCE),--force,)

extract-sample:
	PYTHONPATH=backend backend/.venv/bin/python -m app.extraction.run_extraction --sample --write

init-db:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.init_db

embed-only:
	PYTHONPATH=backend backend/.venv/bin/python -m app.retrieval.embed_only

load-chunks:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.load_chunks

load-graph:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.loader

load-graph-sample:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.loader --file data/extracted/_sample.jsonl

graph-wipe:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.wipe

graph-reset:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.wipe && \
	$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.init_db && \
	$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.load_chunks && \
	$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.loader

graph-report:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python backend/scripts/graph_report.py

dedup-export:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.dedup --export --entities-out $(INPUT)

dedup-offline:
	@set -a && [ -f .env ] && . ./.env; set +a; \
	DRY_RUN=1 EMBED_DEVICE=$(EMBED_DEVICE) PYTHONPATH=backend $(PYTHON) -m app.graph.dedup --input $(INPUT) --plan $(PLAN)

dedup:
	@$(run_with_host_neo4j) \
	DRY_RUN=$(DRY_RUN) PYTHONPATH=backend backend/.venv/bin/python -m app.graph.dedup --plan $(PLAN)

dedup-filter:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python backend/scripts/filter_dedup_plan.py --in $(PLAN) --out $(FILTERED_PLAN)

dedup-apply:
	@$(run_with_host_neo4j) \
	DRY_RUN=$(DRY_RUN) PYTHONPATH=backend backend/.venv/bin/python -m app.graph.dedup --apply --plan $(PLAN)

s3-push:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --push-s3

s3-pull:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --pull-s3

s3-push-embeddings:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --push-embeddings

s3-pull-embeddings:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --pull-embeddings

s3-push-extracted:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --push-extracted

s3-pull-extracted:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --pull-extracted

llm-up:
	docker compose --profile local-llm up -d vllm

llm-smoke:
	@set -a && [ -f .env ] && . ./.env; set +a; \
	python3 scripts/llm_smoke.py

t2c-sample:
	PYTHONPATH=backend backend/.venv/bin/python backend/scripts/t2c_sample.py

synth-sample:
	PYTHONPATH=backend backend/.venv/bin/python backend/scripts/synth_sample.py

ref-queries:
	@set -a && [ -f .env ] && . ./.env; set +a; \
	case "$$NEO4J_URI" in bolt://neo4j:7687) export NEO4J_URI=bolt://localhost:7687 ;; esac; \
	PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_reference_queries.py

mark-reference-chunks:
	@$(run_with_host_neo4j) \
	PYTHONPATH=backend backend/.venv/bin/python backend/scripts/mark_reference_chunks.py
