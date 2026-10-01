# Navbat: one-word commands for running the project. `make help` lists them.
#
#   make        the whole app + Postgres in Docker (migrates and seeds itself)
#   make dev    the app on your machine with auto-reload, Postgres in Docker

.DEFAULT_GOAL := run
.PHONY: run dev db install migrate seed barber test lint format stop reset logs help

VENV   := .venv
BIN    := $(VENV)/bin
# Set by `make dev`; the marker file means "dependencies are installed".
STAMP  := $(VENV)/.installed

run: ## Start app + database in Docker: http://localhost:8000 (Ctrl+C stops it)
	docker compose up --build

dev: db migrate seed ## Local app with auto-reload, database in Docker: http://localhost:8000
	$(BIN)/uvicorn app.main:app --reload

db: ## Start only Postgres and wait until it accepts connections
	docker compose up -d --wait db

# Reinstalls only when pyproject.toml changed since the last install.
$(STAMP): pyproject.toml
	test -d $(VENV) || python3.12 -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"
	touch $(STAMP)

install: $(STAMP) ## Create the virtualenv and install dependencies

migrate: install db ## Apply database migrations
	$(BIN)/alembic upgrade head

seed: migrate ## Fill the database with the demo barbershop (never duplicates)
	$(BIN)/python -m scripts.seed

barber: migrate ## Create a barber: make barber EMAIL=you@x.com NAME="Jasur"
	$(BIN)/python -m scripts.create_barber --email "$(EMAIL)" --name "$(NAME)"

test: install db ## Run the whole test suite
	$(BIN)/pytest

lint: install ## Check lint and formatting
	$(BIN)/ruff check . && $(BIN)/ruff format --check .

format: install ## Fix lint issues and format the code
	$(BIN)/ruff check --fix . && $(BIN)/ruff format .

stop: ## Stop the containers (data is kept)
	docker compose down

reset: ## Stop the containers and DELETE the database
	docker compose down -v

logs: ## Follow the container logs
	docker compose logs -f

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-z-]+):.*## /\1|/' | awk -F'|' '{printf "  make %-9s %s\n", $$1, $$2}'
