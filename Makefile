.PHONY: install test lint fmt typecheck up down logs

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -q

lint:
	ruff check .

fmt:
	ruff format .

typecheck:
	mypy packages/starling_crdt packages/starling_consensus

# Docker node isolation (WP-03 Part 5) — see deploy/README.md.
up:
	docker compose -f deploy/docker-compose.yml up -d

down:
	docker compose -f deploy/docker-compose.yml down

# Usage: make logs NODE=02
logs:
	docker compose -f deploy/docker-compose.yml logs -f node-$(NODE)
