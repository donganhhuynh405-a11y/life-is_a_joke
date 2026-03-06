.PHONY: help install install-dev test test-cov lint format type-check security clean run docker-build docker-up docker-down

# Default target
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# Installation
install: ## Install production dependencies
	pip install -r requirements.txt

install-dev: ## Install development dependencies
	pip install -r requirements.txt -r requirements-test.txt
	pip install black flake8 mypy pylint bandit safety pre-commit
	pre-commit install

install-all: ## Install all optional dependencies
	pip install -e ".[all]"

# Testing
test: ## Run tests
	pytest tests/ -v

test-cov: ## Run tests with coverage report
	pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html --cov-report=xml

test-fast: ## Run tests without slow integration tests
	pytest tests/ -v -m "not slow and not integration"

test-integration: ## Run integration tests only
	pytest tests/test_integration.py -v

test-watch: ## Run tests in watch mode (requires pytest-watch)
	ptw tests/ -- -v

# Code quality
lint: ## Run flake8 linter
	flake8 src/ tests/ tools/

lint-all: ## Run all linters
	flake8 src/ tests/ tools/
	pylint src/ --exit-zero

format: ## Format code with black and isort
	black src/ tests/ tools/ scripts/
	isort src/ tests/ tools/ scripts/

format-check: ## Check formatting without making changes
	black --check src/ tests/ tools/
	isort --check-only src/ tests/ tools/

type-check: ## Run mypy type checker
	mypy src/ --ignore-missing-imports

security: ## Run security scans
	bandit -r src/ -ll
	safety check -r requirements.txt

pre-commit: ## Run pre-commit hooks
	pre-commit run --all-files

# Cleanup
clean: ## Clean build artifacts
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .pytest_cache/ .mypy_cache/ .tox/
	rm -rf htmlcov/ .coverage coverage.xml

clean-models: ## Remove cached ML models
	find models/ -name "*.h5" -delete
	find models/ -name "*.pt" -delete
	find models/ -name "*.pkl" -delete

# Docker
docker-build: ## Build Docker image
	docker build -t trading-bot:latest .

docker-up: ## Start all services with Docker Compose
	docker-compose up -d

docker-up-dev: ## Start development environment
	docker-compose -f docker-compose.dev.yml up -d

docker-up-prod: ## Start production environment
	docker-compose -f docker-compose.prod.yml up -d

docker-down: ## Stop all Docker services
	docker-compose down

docker-logs: ## View Docker logs
	docker-compose logs -f bot

docker-shell: ## Open shell in bot container
	docker-compose exec bot bash

docker-restart: ## Restart bot service
	docker-compose restart bot

# Development
run: ## Run bot in development mode
	python -m src.main

run-paper: ## Run bot in paper trading mode
	ENVIRONMENT=paper python -m src.main

run-backtest: ## Run backtesting
	python -m tools.backtest.cli

setup-dev: ## Setup development environment
	bash scripts/setup/setup_dev.sh

migrate: ## Run database migrations
	python scripts/database/migrate_db.py

api-docs: ## Generate API documentation
	python scripts/generate_api_docs.py

perf-test: ## Run performance benchmarks
	python scripts/performance_test.py

backup: ## Backup data and models
	bash scripts/maintenance/backup_restore.sh backup

restore: ## Restore from backup
	bash scripts/maintenance/backup_restore.sh restore

# Reporting
coverage-html: ## Open HTML coverage report
	open htmlcov/index.html 2>/dev/null || xdg-open htmlcov/index.html 2>/dev/null || echo "Open htmlcov/index.html manually"

# Frontend
frontend-install: ## Install frontend dependencies
	cd frontend && npm install

frontend-dev: ## Start frontend development server
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm run build

frontend-test: ## Run frontend tests
	cd frontend && npm test

# All checks (for CI)
check-all: format-check lint type-check security test-cov ## Run all checks (CI mode)
