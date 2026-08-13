# Common development commands.
#
# A single obvious entry point for routine work — a command people have to
# remember is a command they get wrong.

.PHONY: help setup db-up db-down db-reset migrate migration seed check test test-py test-ts fmt

help:
	@echo "setup      Install all dependencies"
	@echo "db-up      Start PostgreSQL"
	@echo "db-down    Stop PostgreSQL"
	@echo "db-reset   Destroy and recreate the database (local only)"
	@echo "migrate    Apply migrations"
	@echo "migration  Generate a migration:  make migration m='add widgets'"
	@echo "seed       Populate development data"
	@echo "check      Lint, format and typecheck everything"
	@echo "test       Run all tests"
	@echo "fmt        Format everything"

setup:
	pnpm install
	uv sync --dev

db-up:
	docker compose up -d
	@echo "Waiting for PostgreSQL..."
	@until docker exec cairn-postgres pg_isready -U cairn -d cairn >/dev/null 2>&1; do sleep 1; done
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

check:
	pnpm check

test: test-ts test-py

test-ts:
	pnpm test

test-py:
	uv run pytest

fmt:
	pnpm format
	uv run ruff format .
	uv run ruff check --fix .
