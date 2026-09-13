.PHONY: install test lint fmt typecheck

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
