.PHONY: up down ingest extract load-graph test seed-demo s3-push s3-pull

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
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step extract

load-graph:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step load

s3-push:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --push-s3

s3-pull:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --pull-s3
