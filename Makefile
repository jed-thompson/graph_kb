.PHONY: help install dashboard-install dev-install lint ruff ruff-fix format test test-unit test-integration test-property test-cov test-fast test-file \
        docker-up docker-down docker-build docker-rebuild docker-full-rebuild docker-logs docker-logs-app docker-logs-neo4j docker-logs-chroma \
        docker-clean docker-status docker-restart docker-restart-app docker-restart-neo4j docker-restart-chroma \
        neo4j-up neo4j-down neo4j-shell neo4j-reset chroma-up chroma-down chroma-reset \
        infra-up infra-down health run clean check-env \
        db-migrate db-status \
        e2e-test e2e-mock e2e-record e2e-down-mock

# Default target
help:
	@echo "SA-Doc-Generator Makefile"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  install          Install API production dependencies (pip)"
	@echo "  dashboard-install Install dashboard dependencies (npm)"
	@echo "  dev-install      Install all dependencies including dev tools"
	@echo "  check-env        Verify required environment variables are set"
	@echo ""
	@echo "Development:"
	@echo "  run              Run the Chainlit app locally"
	@echo "  lint             Run linting checks (flake8, black, isort)"
	@echo "  ruff             Run ruff linting checks"
	@echo "  ruff-fix         Run ruff with auto-fix (including unsafe fixes)"
	@echo "  clean            Remove cache files and build artifacts"
	@echo ""
	@echo "Testing:"
	@echo "  test             Run all tests"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  test-property    Run property-based tests only"
	@echo "  test-cov         Run tests with coverage report"
	@echo "  test-fast        Run tests excluding slow integration tests"
	@echo ""
	@echo "Docker:"
	@echo "  docker-up        Start all services (app, neo4j, chromadb)"
	@echo "  docker-down      Stop all services"
	@echo "  docker-build     Build Docker images"
	@echo "  docker-rebuild   Rebuild Docker images without cache"
	@echo "  docker-full-rebuild  Stop, build parallel, and start all services"
	@echo "  docker-logs      View logs from all services"
	@echo "  docker-clean     Remove containers, volumes, and images"
	@echo "  docker-restart   Restart all services (or SVC=name for specific)"
	@echo "  docker-restart-app    Restart the app container"
	@echo "  docker-restart-neo4j  Restart Neo4j container"
	@echo "  docker-restart-chroma Restart ChromaDB container"
	@echo ""
	@echo "Individual Services:"
	@echo "  neo4j-up         Start Neo4j only"
	@echo "  neo4j-down       Stop Neo4j"
	@echo "  neo4j-shell      Open Neo4j browser shell"
	@echo "  neo4j-reset      Reset Neo4j data (deletes all data)"
	@echo "  chroma-up        Start ChromaDB only"
	@echo "  chroma-down      Stop ChromaDB"
	@echo "  chroma-reset     Reset ChromaDB data (deletes all data)"
	@echo "  infra-up         Start infrastructure (neo4j + chromadb) without app"
	@echo "  infra-down       Stop infrastructure services"
	@echo ""
	@echo "Database:"
	@echo "  db-migrate       Apply all pending Alembic migrations (upgrade head)"
	@echo "  db-status        Show current Alembic migration revision"
	@echo ""
	@echo "Health & Status:"
	@echo "  health           Check if all services are responding"
	@echo "  docker-status    Show status of Docker containers"
	@echo ""
	@echo "E2E Tests (Playwright):"
	@echo "  e2e-test         Run E2E tests with live LLM calls"
	@echo "  e2e-mock         Run E2E tests with pre-recorded LLM mocks"
	@echo "  e2e-record       Start API in record mode + run E2E tests (captures LLM responses)"
	@echo "  e2e-down-mock    Stop mock-mode API and restart in normal mode"

# ============================================================================
# Setup & Installation
# ============================================================================

install:
	pip install -r requirements.api.txt

dashboard-install:
	cd graph_kb_dashboard && npm install

dev-install: install dashboard-install
	pip install black isort flake8 mypy pytest-cov

check-env:
	@echo "Checking environment variables..."
	@test -n "$(OPENAI_API_KEY)" || (echo "ERROR: OPENAI_API_KEY not set" && exit 1)
	@echo "✓ OPENAI_API_KEY is set"
	@test -n "$(NEO4J_URI)" || echo "⚠ NEO4J_URI not set (using default: bolt://localhost:7687)"
	@test -n "$(NEO4J_PASSWORD)" || echo "⚠ NEO4J_PASSWORD not set (using default: password)"
	@echo "Environment check complete"

# ============================================================================
# Development
# ============================================================================

run:
	PYTHONPATH=. chainlit run src/app.py -w --host 0.0.0.0 --port 8090

lint:
	@echo "Running flake8..."
	flake8 src/ tests/ --max-line-length=120 --ignore=E501,W503
	@echo "Running black check..."
	black --check src/ tests/
	@echo "Running isort check..."
	isort --check-only src/ tests/

ruff:
	@echo "Running ruff linting..."
	ruff check graph_kb_api/ graph_kb_dashboard/src/

ruff-fix:
	@echo "Running ruff with auto-fix..."
	ruff check graph_kb_api/ graph_kb_dashboard/src/ --fix --unsafe-fixes

format:
	black src/ tests/
	isort src/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".hypothesis" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml 2>/dev/null || true
	@echo "Cleaned cache files"

# ============================================================================
# Testing
# ============================================================================

test:
	PYTHONPATH=. pytest tests/ -v

test-unit:
	PYTHONPATH=. pytest tests/unit/ -v

test-integration:
	PYTHONPATH=. pytest tests/integration/ -v

test-property:
	PYTHONPATH=. pytest tests/property/ -v

test-cov:
	PYTHONPATH=. pytest tests/ -v --cov=src --cov-report=html --cov-report=term-missing

test-fast:
	PYTHONPATH=. pytest tests/unit/ tests/property/ -v

# Run specific test file
test-file:
	@test -n "$(FILE)" || (echo "Usage: make test-file FILE=tests/unit/test_example.py" && exit 1)
	PYTHONPATH=. pytest $(FILE) -v

# ============================================================================
# Docker - Full Stack
# ============================================================================

docker-up:
	docker compose up -d
	@echo ""
	@echo "Services starting..."
	@echo "  App:      http://localhost:8090"
	@echo "  Neo4j:    http://localhost:7474 (browser)"
	@echo "  ChromaDB: http://localhost:8091"
	@echo "  VectorAdmin: http://localhost:3001"

docker-down:
	docker compose down

docker-build:
	docker compose build

docker-rebuild:
	docker compose build --no-cache

docker-full-rebuild:
	docker compose down
	docker compose build --parallel
	docker compose up

docker-logs:
	docker compose logs -f

docker-logs-app:
	docker compose logs -f agent

docker-logs-neo4j:
	docker compose logs -f neo4j

docker-logs-chroma:
	docker compose logs -f chromadb

docker-clean:
	docker compose down -v --rmi local
	@echo "Removed containers, volumes, and local images"

docker-status:
	docker compose ps

docker-restart:
	docker compose restart

docker-restart-app:
	docker compose restart agent

docker-restart-neo4j:
	docker compose restart neo4j

docker-restart-chroma:
	docker compose restart chromadb

# ============================================================================
# Individual Services
# ============================================================================

neo4j-up:
	docker compose up -d neo4j
	@echo "Neo4j starting at http://localhost:7474"

neo4j-down:
	docker compose stop neo4j

neo4j-shell:
	@echo "Opening Neo4j browser at http://localhost:7474"
	@open http://localhost:7474 2>/dev/null || xdg-open http://localhost:7474 2>/dev/null || echo "Visit http://localhost:7474"

chroma-up:
	docker compose up -d chromadb
	@echo "ChromaDB starting at http://localhost:8091"

chroma-down:
	docker compose stop chromadb

infra-up:
	docker compose up -d neo4j chromadb
	@echo ""
	@echo "Infrastructure services starting..."
	@echo "  Neo4j:    http://localhost:7474"
	@echo "  ChromaDB: http://localhost:8091"

infra-down:
	docker compose stop neo4j chromadb

# ============================================================================
# Database Management
# ============================================================================

# Get compose project name (defaults to directory name)
COMPOSE_PROJECT := graphkb
COMPOSE_PROJECT := $(or $(COMPOSE_PROJECT_NAME),$(COMPOSE_PROJECT))

db-migrate:
	PYTHONPATH=. alembic upgrade head

db-status:
	PYTHONPATH=. alembic current

neo4j-reset:
	@echo "WARNING: This will delete all Neo4j data!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	docker compose stop neo4j
	docker volume rm $(COMPOSE_PROJECT)_neo4j_data 2>/dev/null || true
	docker compose up -d neo4j
	@echo "Neo4j data reset complete"

chroma-reset:
	@echo "WARNING: This will delete all ChromaDB data!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	docker compose stop chromadb
	docker volume rm $(COMPOSE_PROJECT)_chromadb_data 2>/dev/null || true
	docker compose up -d chromadb
	@echo "ChromaDB data reset complete"

# ============================================================================
# Health Checks
# ============================================================================

health:
	@echo "Checking service health..."
	@curl -s http://localhost:7474 > /dev/null && echo "✓ Neo4j is running" || echo "✗ Neo4j is not responding"
	@curl -s http://localhost:8091/api/v1/heartbeat > /dev/null && echo "✓ ChromaDB is running" || echo "✗ ChromaDB is not responding"
	@curl -s http://localhost:8090 > /dev/null && echo "✓ App is running" || echo "✗ App is not responding"

# ============================================================================
# E2E Tests (Playwright)
# ============================================================================

e2e-test:
	@echo "Running E2E tests with live LLM calls..."
	cd e2e && npx playwright test

e2e-mock:
	@echo "Starting API with mock LLM mode..."
	@set LLM_RECORDING_MODE=mock && docker compose up -d --build api
	@echo "Waiting for API to be healthy..."
	@ping -n 6 127.0.0.1 >nul 2>&1
	cd e2e && npx playwright test --config=playwright.mock.config.ts
	@echo "Restarting API in normal mode..."
	@set LLM_RECORDING_MODE=off && docker compose up -d --build api

e2e-record:
	@echo "Starting API in recording mode (captures LLM responses)..."
	@set LLM_RECORDING_MODE=record && docker compose up -d --build api
	@echo "Waiting for API to be healthy..."
	@ping -n 6 127.0.0.1 >nul 2>&1
	cd e2e && npx playwright test
	@echo "Recordings saved to e2e/tests/fixtures/llm-responses/"

e2e-down-mock:
	@echo "Restarting API in normal mode..."
	@set LLM_RECORDING_MODE=off && docker compose up -d --build api
