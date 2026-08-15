# Common development commands.
#
# A single obvious entry point for routine work — a command people have to
# remember is a command they get wrong.

.PHONY: help setup dev db-up db-down db-reset migrate migration seed schema serve worker eval queue-up queue-down check test test-py test-ts fmt

help:
	@echo "setup      Install all dependencies"
	@echo "dev        Design system preview on :6006"
	@echo "db-up      Start PostgreSQL"
	@echo "db-down    Stop PostgreSQL"
	@echo "db-reset   Destroy and recreate the database (local only)"
	@echo "migrate    Apply migrations"
	@echo "migration  Generate a migration:  make migration m='add widgets'"
	@echo "seed       Populate development data"
	@echo "schema     Regenerate the event schema, OpenAPI document and TypeScript client"
	@echo "serve      Run the API locally on :8000 with reload"
	@echo "worker     Run a job worker"
	@echo "eval       Run the AI evaluation harness (pipeline=reference|broken)"
	@echo "queue-up   Start the Pub/Sub emulator"
	@echo "check      Lint, format and typecheck everything"
	@echo "test       Run all tests"
	@echo "fmt        Format everything"

setup:
	cp -n .env.example .env || true
	pnpm install
	uv sync --dev

# The design system, in isolation. Components are reviewed here before any
# screen exists.
dev:
	pnpm --filter @cairn/ui dev

db-up:
	docker compose up -d
	@echo "Waiting for PostgreSQL..."
	@i=0; until docker exec cairn-postgres pg_isready -U cairn -d cairn >/dev/null 2>&1; do \n		i=$$((i+1)); \n		if [ $$i -gt 60 ]; then echo "PostgreSQL did not become ready. Is port 5432 already in use?"; exit 1; fi; \n		sleep 1; \n	done
	@docker exec cairn-postgres psql -U cairn -d postgres -c "CREATE DATABASE cairn_test" >/dev/null 2>&1 || true
	@docker exec cairn-postgres psql -U cairn -d postgres -c "CREATE DATABASE cairn_migrations" >/dev/null 2>&1 || true
	@echo "PostgreSQL ready."

db-down:
	docker compose down

# Destroys data. Local only — production data never reaches a local
# environment (md/17-engineering-standards.md §9.1).
db-reset:
	docker compose down -v
	$(MAKE) db-up
	$(MAKE) migrate
	$(MAKE) seed

migrate:
	cd apps/api && uv run alembic upgrade head

migration:
	@test -n "$(m)" || (echo "Usage: make migration m='describe the change'" && exit 1)
	cd apps/api && uv run alembic revision --autogenerate -m "$(m)"
	@echo "Review the generated file before committing — autogenerate is a draft, not an answer."

seed:
	uv run python -m cairn_api.db.seed

# Python is the source of truth for both contracts; every artefact below is
# generated from it and committed, so a contract change is visible in review.
#
# Two independent contracts:
#   - the ActivityEvent JSON Schema, shared by the ingestion pipeline
#   - the API's OpenAPI document, from which the TypeScript client is generated
#
# Run this after changing a Pydantic model or a route. A test fails if you
# forget, so the schema cannot silently go stale.
schema:
	uv run python -m cairn_api.events.export_schema
	pnpm --filter @cairn/types generate
	uv run python -m cairn_api.api.export_openapi
	pnpm --filter @cairn/api-client generate
# Both generators write unformatted output, so without this the documented way
# to regenerate the client leaves the repository failing `pnpm check` — a CI
# round-trip for anyone who touches the API surface.
	pnpm -s format

# Run the API locally with reload. Port 8000 to leave 3000 for the web app and
# 6006 for the design system preview.
serve:
	uv run uvicorn --factory cairn_api.api:create_app --reload --port 8000

# Run the AI evaluation harness against the golden dataset.
#
# Exits non-zero when the release gate blocks, so it is usable as a gate rather
# than as a report someone reads and moves on from.
eval:
	uv run python -m cairn_api.evaluation.runner --pipeline $(or $(pipeline),reference)

# Run a job worker. A separate process from the API on purpose: they scale on
# different signals (requests vs queue depth), and a worker crash must not take
# the API down with it.
worker:
	uv run python -m cairn_api.jobs.main

# The Pub/Sub emulator, so the production broker is exercised locally rather
# than assumed. Tests against it skip when it is not running.
queue-up:
	docker compose up -d pubsub
	@echo "Emulator on localhost:8085. Export PUBSUB_EMULATOR_HOST=localhost:8085 to use it."

queue-down:
	docker compose stop pubsub

check:
	pnpm check

test: db-up test-ts test-py

test-ts:
	pnpm test

test-py:
	uv run pytest

fmt:
	pnpm format
	uv run ruff format .
	uv run ruff check --fix .
