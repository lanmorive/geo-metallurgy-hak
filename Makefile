.PHONY: up down ingest extract load-graph test seed-demo

up:
	docker compose up -d --build

down:
	docker compose down

test:
	cd backend && .venv/bin/python -m pytest tests/test_e2e.py -v

seed-demo:
	PYTHONPATH=backend backend/.venv/bin/python scripts/seed_demo.py

ingest:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step ingest

extract:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step extract

load-graph:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step load
