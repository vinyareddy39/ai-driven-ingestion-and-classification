.PHONY: help up down test eval load demo clean scaffold generate-data train

PYTHON ?= python

help:
	@echo "Available targets:"
	@echo "  make up          - Start the stack with docker compose (or background local services)"
	@echo "  make down        - Stop the docker compose stack"
	@echo "  make test        - Run unit and integration tests with pytest"
	@echo "  make eval        - Run locked test set evaluation and generate audit report"
	@echo "  make load        - Run load test benchmark for 50,000 docs/day equivalence"
	@echo "  make demo        - Ingest sample documents and launch the HTMX review UI"
	@echo "  make scaffold    - Verify scaffolding and directory structure"
	@echo "  make generate-data - Generate synthetic multi-format documents and train/val/test splits"
	@echo "  make train       - Train classification model and tune per-class thresholds"

up:
	docker-compose up -d

down:
	docker-compose down

scaffold:
	$(PYTHON) -c "import app; print('Scaffolding verified.')"

generate-data:
	$(PYTHON) -m data.synthetic_generator

train:
	$(PYTHON) -m app.models.classifier_train

dev-backend:
	cd backend && $(PYTHON) -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

test:
	cd backend && $(PYTHON) -m pytest -v tests/

eval:
	$(PYTHON) -m tests.evaluation_runner

load:
	$(PYTHON) -m tests.load_runner

demo:
	$(PYTHON) -m app.api.demo_runner
