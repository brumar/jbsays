.PHONY: help install dev test test-cov lint format check clean build docs

help:  ## Display this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package in production mode
	pip install -e .

dev:  ## Install the package in development mode with all dependencies
	pip install -e ".[dev,docs]"

test:  ## Run tests
	pytest -v

test-cov:  ## Run tests with coverage
	pytest --cov=mware --cov-report=term-missing --cov-report=html

lint:  ## Run linters (black, isort, ruff, mypy)
	@echo "Running black check..."
	black --check --diff .
	@echo "Running isort check..."
	isort --check-only --diff .
	@echo "Running ruff check..."
	ruff check .
	@echo "Running mypy check..."
	mypy .

format:  ## Format code (black, isort, ruff)
	@echo "Running isort..."
	isort .
	@echo "Running black..."
	black .
	@echo "Running ruff..."
	ruff check --fix .

check: lint test  ## Run all checks (lint + test)

watch-test:  ## Run tests in watch mode
	pytest-watch --clear --nobeep --runner "pytest -v"

build:  ## Build distribution packages
	python -m build

clean:  ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

docs-build:  ## Build documentation
	mkdocs build

docs-serve:  ## Serve documentation locally
	mkdocs serve --dev-addr localhost:8000

release:  ## Create a new release (use with VERSION=x.y.z)
	@if [ -z "$(VERSION)" ]; then echo "Please specify VERSION=x.y.z"; exit 1; fi
	@echo "Releasing version $(VERSION)..."
	@echo "Updating version in src/mware/__init__.py..."
	@sed -i 's/__version__ = ".*"/__version__ = "$(VERSION)"/' src/mware/__init__.py
	@echo "Creating git commit and tag..."
	git add src/mware/__init__.py
	git commit -m "Bump version to $(VERSION)"
	git tag -a v$(VERSION) -m "Release version $(VERSION)"
	@echo "Building package..."
	python -m build
	@echo "Release prepared. Push with: git push && git push --tags"

# Development shortcuts
.PHONY: t tc l f c

t: test  ## Shortcut for test
tc: test-cov  ## Shortcut for test-cov
l: lint  ## Shortcut for lint
f: format  ## Shortcut for format
c: check  ## Shortcut for check