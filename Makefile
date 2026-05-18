.PHONY: help install dev test build up down logs ps shell health smoke clean

DC := docker compose

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Local Python (no Docker) ──────────────────────────────────────────────
install: ## Install dev deps in .venv
	python -m venv .venv
	. .venv/bin/activate && pip install -r requirements-dev.txt

dev: ## Run uvicorn locally with hot-reload
	. .venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

test: ## Run the full pytest suite
	. .venv/bin/activate && pytest -v

# ── Docker ─────────────────────────────────────────────────────────────────
build: ## Build the Docker image
	$(DC) build

up: ## Start the service in the background
	$(DC) up -d

down: ## Stop and remove the container
	$(DC) down

logs: ## Tail container logs
	$(DC) logs -f --tail=100

ps: ## Show service status
	$(DC) ps

shell: ## Open a shell inside the running container
	$(DC) exec ocr sh

# ── Smoke tests against the running service ───────────────────────────────
health: ## curl the readiness endpoint
	curl -fsS http://localhost:8000/v1/health/ready && echo

smoke: ## End-to-end smoke test (requires sample.jpg and INTERNAL_SECRET in env)
	@test -f sample.jpg || (echo "Put a test image at ./sample.jpg first" && exit 1)
	@test -n "$$INTERNAL_SECRET" || (echo "export INTERNAL_SECRET first" && exit 1)
	curl -X POST http://localhost:8000/v1/ocr/extract \
		-H "X-Internal-Secret: $$INTERNAL_SECRET" \
		-F "file=@sample.jpg" \
		-F "doc_type=permis"

clean: ## Remove caches and the built image
	rm -rf .pytest_cache __pycache__ */__pycache__
	$(DC) down --rmi local --volumes --remove-orphans 2>/dev/null || true
