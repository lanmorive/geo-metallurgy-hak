.PHONY: up down init-db embed-only ingest extract extract-core extract-sample load-chunks load-graph load-graph-sample test seed-demo s3-push s3-pull s3-push-embeddings s3-pull-embeddings s3-push-extracted s3-pull-extracted llm-up llm-smoke t2c-sample synth-sample

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
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.init_db

embed-only:
	PYTHONPATH=backend backend/.venv/bin/python -m app.retrieval.embed_only

load-chunks:
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.load_chunks

load-graph:
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.loader

load-graph-sample:
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.loader --file data/extracted/_sample.jsonl

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
