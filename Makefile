# Makefile for Twitch ColorChanger Bot Development

.PHONY: help install install-dev lint format security check-all clean build docker-build docker-run

# Default target
help:
	@echo "Available targets:"
	@echo "  install         - Install production dependencies"
	@echo "  install-dev     - Install development dependencies"
	@echo "  lint            - Run all linting tools"
	@echo "  format          - Format code with black and isort"
	@echo "  security        - Run security checks"
	@echo "  check-all       - Run all quality checks"
	@echo "  clean           - Clean temporary files"
	@echo "  build           - Build package"
	@echo "  docker-build    - Build Docker image"
	@echo "  docker-run      - Run Docker container"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

# Code quality
lint:
	@echo "Running flake8..."
	flake8 src/ tests/
	@echo "Running mypy..."
	mypy src/
	@echo "Running bandit..."
	bandit -r src/
	@echo "Running safety..."
	safety check

format:
	@echo "Formatting with black..."
	black src/ tests/
	@echo "Sorting imports with isort..."
	isort src/ tests/

format-check:
	black --check src/ tests/
	isort --check-only src/ tests/

security:
	bandit -r src/
	safety check

# Comprehensive checks
check-all: format-check lint security
	@echo "All checks passed!"

# Run comprehensive checks (linting only)
check: lint
	@echo "✅ All checks passed!"

# Clean artifacts
clean:
	rm -rf .cache/ .tox/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

.PHONY: help install install-dev lint format format-check security check-all check clean build docker-build docker-run dev-setup pre-commit dev-check ci docs docs-serve profile version check-env

# Build
build: clean
	python -m build

# Docker
docker-build:
	docker build -t twitch-colorchanger .

docker-run:
	docker run -v "$(PWD)/config:/app/config" twitch-colorchanger

# Development helpers
dev-setup: install-dev
	@echo "Setting up pre-commit hooks..."
	pre-commit install
	@echo "Development environment ready!"

pre-commit:
	pre-commit run --all-files

# Quick development cycle
dev-check: format lint test-unit
	@echo "Quick development checks passed!"

# CI/CD simulation
ci: install-dev check-all
	@echo "CI checks completed successfully!"

# Performance testing
perf-test:
	pytest -m slow -v

# Generate test data
generate-fixtures:
	@echo "Generating test fixtures..."
	python -c "from tests.fixtures import *; print('Test fixtures ready')"

# Database/Config helpers
validate-config:
	python -c "from src.config import get_configuration; from src.config_validator import validate_all_users; users = get_configuration(); print('Config valid:', validate_all_users(users))"

# Documentation
docs:
	@echo "Building documentation..."
	sphinx-build -b html docs/ docs/_build/

docs-serve:
	python -m http.server 8000 --directory docs/_build/

# Monitoring
profile:
	py-spy record -o profile.svg -- python -m src.main &
	@echo "Profiling started. Stop with 'pkill py-spy'"

# Version management
version:
	@echo "Current version: $(shell python -c 'import src; print(getattr(src, "__version__", "unknown"))')"

# Environment checks
check-env:
	@echo "Python version: $(shell python --version)"
	@echo "Pip version: $(shell pip --version)"
	@echo "Virtual environment: $(VIRTUAL_ENV)"
	@echo "Dependencies:"
	@pip list | grep -E "(pytest|aiohttp|watchdog)"
