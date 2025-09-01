# Makefile for Twitch ColorChanger Bot Development

.PHONY: help install install-dev lint format format-check security check-all check clean build docker-build docker-run dev-setup pre-commit dev-check ci validate-config docs docs-serve profile version check-env

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
	@echo "  validate-config - Validate configuration file"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

# Code quality
lint:
	@echo "Running flake8..."
	flake8 src/
	@echo "Running mypy..."
	mypy src/
	@echo "Running bandit..."
	bandit -r src/

format:
	@echo "Formatting with black..."
	black src/
	@echo "Sorting imports with isort..."
	isort src/

format-check:
	black --check src/
	isort --check-only src/

security:
	bandit -r src/
# Comprehensive checks
check-all: format-check lint security
	@echo "All checks passed!"

# Run comprehensive checks (linting only)
check: lint
	@echo "✅ All checks passed!"

# Clean artifacts
clean:
	rm -rf .cache/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

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
dev-check: format lint
	@echo "Quick development checks passed!"

# CI/CD simulation
ci: install-dev check-all
	@echo "CI checks completed successfully!"

# Configuration validation
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
	@pip list | grep -E "(aiohttp|watchdog|black|flake8|mypy|bandit)"
