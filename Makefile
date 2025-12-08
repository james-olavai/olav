.PHONY: help build up down logs test test-e2e test-unit clean restart health quickstart deploy doctor

# Default target
help:
	@echo "OLAV (NetAIChatOps) Management Commands"
	@echo "========================================"
	@echo ""
	@echo "Quick Start:"
	@echo "make quickstart     - One-command setup (recommended for new users)"
	@echo "make deploy         - Full deployment with NetBox + API server"
	@echo "make doctor         - Check all dependencies and connections"
	@echo ""
	@echo "Docker:"
	@echo "make build          - Build all Docker images"
	@echo "make up             - Start all services"
	@echo "make down           - Stop all services"
	@echo "make logs           - View logs (all services)"
	@echo "make logs-api       - View API server logs"
	@echo "make health         - Check service health"
	@echo "make clean          - Remove containers and volumes"
	@echo "make restart        - Restart all services"
	@echo ""
	@echo "Testing:"
	@echo "make test           - Run E2E tests in container"
	@echo "make test-unit      - Run unit tests locally"
	@echo ""
	@echo "Code Quality:"
	@echo "make lint           - Run ruff linter"
	@echo "make lint-fix       - Run ruff with auto-fix"
	@echo "make format         - Format code with ruff"
	@echo "make check          - Full quality check (lint + format)"
	@echo ""
	@echo "Development:"
	@echo "make dev            - Start in development mode (hot reload)"
	@echo "make shell-api      - Shell into API container"
	@echo "make shell-tests    - Shell into tests container"

# Build images
build:
	docker-compose build

# Start services
up:
	docker-compose up -d postgres opensearch redis olav-api
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@docker-compose ps

# Start in development mode
dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Stop services
down:
	docker-compose down

# View logs
logs:
	docker-compose logs -f

logs-api:
	docker-compose logs -f olav-api

# Run E2E tests
test:
	@echo "Running E2E tests in container..."
	docker-compose --profile testing run --rm olav-tests

# Run E2E tests with basic suite
test-basic:
	docker-compose --profile testing run --rm olav-tests pytest tests/e2e/test_api_basic.py -v

# Run unit tests locally
test-unit:
	uv run pytest tests/unit/ -v

# Lint and format checks
lint:
	uv run ruff check src/ tests/

lint-fix:
	uv run ruff check src/ tests/ --fix

format:
	uv run ruff format src/ tests/

format-check:
	uv run ruff format src/ tests/ --check

# Type checking
typecheck:
	uv run mypy src/ --ignore-missing-imports

# Full quality check (lint + format + type)
check: lint-fix format
	@echo "✓ Code quality checks passed"

# Check health
health:
	@echo "Checking service health..."
	@docker-compose ps
	@echo ""
	@echo "PostgreSQL:"
	@docker-compose exec postgres pg_isready -U olav || echo "❌ Not ready"
	@echo ""
	@echo "OpenSearch:"
	@curl -s http://localhost:9200/_cluster/health?pretty || echo "❌ Not accessible"
	@echo ""
	@echo "Redis:"
	@docker-compose exec redis redis-cli ping || echo "❌ Not ready"
	@echo ""
	@echo "API Server:"
	@curl -s http://localhost:8000/health | python -m json.tool || echo "❌ Not accessible"

# Clean up
clean:
	docker-compose down -v
	docker system prune -f

# Restart services
restart:
	docker-compose restart

# Shell access
shell-api:
	docker-compose exec olav-api /bin/bash

shell-tests:
	docker-compose --profile testing run --rm olav-tests /bin/bash

# Initialize database
init-db:
	docker-compose exec postgres psql -U olav -d olav -c "\dt"

# View API docs
docs:
	@echo "Opening API documentation..."
	@echo "Swagger UI: http://localhost:8000/docs"
	@echo "ReDoc: http://localhost:8000/redoc"

# ============================================
# Quick Start Commands
# ============================================

# One-command setup for new users
quickstart:
	@echo ""
	@echo "🚀 OLAV (NetAIChatOps) Quick Start"
	@echo "==================================="
	@echo ""
	@if [ ! -f .env ]; then \
		echo "📋 Creating .env from template..."; \
		cp .env.example .env; \
		echo "⚠️  Please edit .env and set LLM_API_KEY before continuing"; \
		echo "   Then run 'make quickstart' again"; \
		exit 1; \
	fi
	@echo "📦 Installing dependencies..."
	uv sync
	@echo ""
	@echo "🐳 Starting Docker services..."
	docker-compose up -d opensearch postgres redis
	@echo ""
	@echo "⏳ Waiting for services to be healthy (30s)..."
	@sleep 30
	@echo ""
	@echo "🔧 Initializing database and indexes..."
	uv run olav --init
	@echo ""
	@echo "✅ Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Start CLI:     uv run olav"
	@echo "  2. Start Server:  make deploy"
	@echo "  3. Check health:  make doctor"
	@echo ""

# Full deployment with NetBox and API server
deploy:
	@echo ""
	@echo "🚀 OLAV Full Deployment"
	@echo "======================="
	@echo ""
	@echo "Starting NetBox stack..."
	docker-compose --profile netbox up -d
	@echo ""
	@echo "⏳ Waiting for NetBox to initialize (60s)..."
	@sleep 60
	@echo ""
	@echo "Initializing NetBox integration..."
	uv run olav --init-netbox || echo "⚠️  NetBox init skipped (may already be configured)"
	@echo ""
	@echo "Starting API server..."
	docker-compose up -d olav-server
	@echo ""
	@echo "⏳ Waiting for API server (10s)..."
	@sleep 10
	@echo ""
	@echo "✅ Deployment complete!"
	@echo ""
	@echo "Services:"
	@echo "  - API Server:  http://localhost:8001"
	@echo "  - API Docs:    http://localhost:8001/docs"
	@echo "  - NetBox:      http://localhost:8080"
	@echo "  - SuzieQ GUI:  http://localhost:8501"
	@echo ""

# Health check for all dependencies
doctor:
	@echo ""
	@echo "🩺 OLAV System Health Check"
	@echo "============================"
	@echo ""
	uv run olav doctor