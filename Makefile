.PHONY: install test lint fmt typecheck up down logs proto headline

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

# Regenerate the protobuf Python bindings (WP-04 Part 1). Generated files
# ARE committed (packages/starling_proto/generated/) so protoc/grpcio-tools
# is a dev-only dependency, never required at install time.
proto:
	python -m grpc_tools.protoc \
		-I packages/starling_proto \
		--python_out=packages/starling_proto/generated \
		--pyi_out=packages/starling_proto/generated \
		packages/starling_proto/starling.proto

# Docker node isolation (WP-03 Part 5) — see deploy/README.md.
up:
	docker compose -f deploy/docker-compose.yml up -d

down:
	docker compose -f deploy/docker-compose.yml down

# Usage: make logs NODE=02
logs:
	docker compose -f deploy/docker-compose.yml logs -f node-$(NODE)

# The headline three-way experiment (WP-14 Part 4): baseline vs. Starling
# healthy vs. Starling partitioned+Byzantine. Long — arm 3 needs
# `docker compose` for real partition/attack events. See
# docs/results_headline.md for how the output gets written up.
headline:
	python scripts/run_headline.py --repeat 5 --out results/headline
