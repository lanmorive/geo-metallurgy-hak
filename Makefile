.PHONY: up down init-db ingest extract extract-core extract-sample load-graph test seed-demo s3-push s3-pull llm-up llm-smoke

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
	PYTHONPATH=backend backend/.venv/bin/python -m app.extraction.run_extraction --sample

init-db:
	PYTHONPATH=backend backend/.venv/bin/python -m app.graph.init_db

load-graph:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step load

s3-push:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --push-s3

s3-pull:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --pull-s3

llm-up:
	docker compose --profile local-llm up -d vllm

llm-smoke:
	@set -a && [ -f .env ] && . ./.env; set +a; \
	python3 scripts/llm_smoke.py
