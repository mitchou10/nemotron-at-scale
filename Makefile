.DEFAULT_GOAL := help

PROJECTS := backend vosk_service

.PHONY: help install-hooks check gitleaks lint test up down

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install-hooks: ## Install the git hooks: ruff, gitleaks, Conventional Commits check
	@command -v pre-commit >/dev/null 2>&1 || uv tool install pre-commit
	pre-commit install

check: ## Run every pre-commit hook on every file (ruff, gitleaks, yaml, ...)
	pre-commit run --all-files

gitleaks: ## Scan the whole git history for secrets, like the CI does
	docker run --rm -v "$(CURDIR):/repo" -w /repo ghcr.io/gitleaks/gitleaks:v8.30.1 \
		git . --config .gitleaks.toml --redact --no-banner

lint: ## Lint and format-check both Python projects (ruff)
	@for p in $(PROJECTS); do \
		echo "== $$p"; \
		(cd $$p && uv run --extra dev ruff check . && uv run --extra dev ruff format --check .) || exit 1; \
	done

test: ## Run the tests of both Python projects
	@for p in $(PROJECTS); do \
		echo "== $$p"; \
		(cd $$p && uv run --extra dev pytest) || exit 1; \
	done

up: ## Start the stack with the Vosk profile (see docker-compose.yml for the others)
	docker compose --profile vosk up --build

down: ## Stop the stack
	docker compose --profile vosk down
