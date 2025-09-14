# Makefile for Twitch ColorChanger Bot Development

.PHONY: help install install-dev lint security check-all check clean build docker-build docker-run dev-setup pre-commit dev-check ci validate-config docs docs-serve profile version check-env ruff-lint ruff-format ruff-check md-format md-check vulture-check package-clean

# Default target
help:
	@echo "Available targets:"
	@echo "  install         - Install production dependencies"
	@echo "  install-dev     - Install development dependencies"
	@echo "  lint            - Run all linting tools (Ruff, mypy, bandit)"
	@echo "  ruff-lint       - Run Ruff linter with auto-fix"
	@echo "  ruff-format     - Format code with Ruff"
	@echo "  ruff-check      - Check code with Ruff (lint + format check)"
	@echo "  md-format       - Format Markdown files"
	@echo "  md-check        - Check Markdown formatting"
	@echo "  vulture-check   - Run dead code detection with Vulture"
	@echo "  security        - Run security checks"
	@echo "  check-all       - Run all Python quality checks"
	@echo "  clean           - Clean temporary files"
	@echo "  build           - Build package"
	@echo "  docker-build    - Build Docker image"
	@echo "  docker-run      - Run Docker container"
	@echo "  validate-config - Validate configuration file"
	@echo "  package-clean   - Remove build, dist, egg-info and reinstall editable"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

# Code quality
lint:
	@echo "Running Ruff linter..."
	.venv/bin/python -m ruff check src/
	@echo "Running mypy..."
	.venv/bin/python -m mypy src/
	@echo "Running bandit (security scan)..."
	.venv/bin/python -m bandit -q -r src/ scripts/ || true

# Vulture dead code detection
vulture-check:
	@echo "🦢 Running vulture for dead code detection..."
	.venv/bin/vulture src/ --min-confidence 70

# Ruff commands (modern alternative)
ruff-lint:
	@echo "Running Ruff linter..."
	.venv/bin/python -m ruff check src/ --fix

ruff-format:
	@echo "Formatting with Ruff..."
	.venv/bin/python -m ruff format src/

ruff-check:
	@echo "Running Ruff checks..."
	.venv/bin/python -m ruff check src/
	.venv/bin/python -m ruff format src/ --check

# Markdown formatting commands
md-format:
	@echo "Formatting Markdown files..."
	.venv/bin/python -m mdformat README.md FUNCTIONAL_DOCUMENTATION.md

md-check:
	@echo "Checking Markdown formatting..."
	.venv/bin/python -m mdformat --check README.md FUNCTIONAL_DOCUMENTATION.md

security:
	.venv/bin/python -m bandit -q -r src/ scripts/

# Comprehensive checks
check-all: ruff-check lint vulture-check security
	@echo "All Python checks passed!"
	@echo "Note: Run 'make md-check' separately to check Markdown formatting"

# Run comprehensive checks (linting only)
check: lint
	@echo "✅ All checks passed!"

# Clean artifacts
clean:
	rm -rf .cache/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete
	rm -rf build/
	rm -rf dist/
	find . -maxdepth 3 -type d -name "*.egg-info" -exec rm -rf {} +

# Packaging cleanup & editable reinstall
package-clean: clean
	@echo "Cleaning packaging artifacts and reinstalling in editable mode..."
	python -m pip install -e .

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
dev-check: ruff-check lint
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
	@pip list | grep -E "(aiohttp|ruff|mypy|bandit|mdformat)"
