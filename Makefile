# AI Software Engineering Agent - developer commands.
#
# The three local modes of section 36:
#   make dev-infra + make api + make worker   -> Mode A (debugging)
#   make compose-up                           -> Mode B (integration)
#   make k8s-apply                            -> Mode C (scalability)

PYTHON ?= python
VENV   ?= .venv
BIN    := $(VENV)/Scripts
SANDBOX := .sandbox/order-service

ifeq ($(OS),)
	BIN := $(VENV)/bin
endif

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- environment

.PHONY: install
install: ## Create the virtualenv and install the platform
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]"

.PHONY: bootstrap
bootstrap: ## Create the schema and the sample repository checkout
	$(BIN)/python -m scripts.bootstrap

.PHONY: reset
reset: ## Drop the schema, clear workspaces, prune agent worktrees
	$(BIN)/python -m scripts.reset_poc --all

# ------------------------------------------------------------------- run local

.PHONY: dev-infra
dev-infra: ## Mode A: PostgreSQL + Redis in Docker, everything else on the host
	docker compose up -d postgres redis

.PHONY: api
api: ## Run the API (http://localhost:8000/docs)
	$(BIN)/python -m uvicorn apps.api.main:app --reload --port 8000

.PHONY: worker
worker: ## Run one agent worker; run this in several terminals to scale out
	$(BIN)/python -m apps.worker.main

.PHONY: run-local
run-local: ## API + worker in one process (needed when REDIS_URL=memory://)
	$(BIN)/python -m scripts.run_local

.PHONY: web
web: ## Run the Next.js UI (http://localhost:3000)
	cd apps/web && npm install && npm run dev

.PHONY: demo
demo: ## Submit the sample issue and follow the timeline
	$(BIN)/python -m scripts.submit_task --watch \
		--repository-path "$(SANDBOX)" \
		--issue "Cancelling an order that is already cancelled returns HTTP 500 instead of succeeding. Make cancellation idempotent and add a regression test."

.PHONY: index
index: ## Index the sample repository for retrieval
	$(BIN)/python -m scripts.index_repository --path "$(SANDBOX)" --query "cancel order"

# ---------------------------------------------------------------------- checks

.PHONY: test
test: ## Run every test except the slow dotnet ones
	$(BIN)/python -m pytest -q -m "not slow"

.PHONY: test-all
test-all: ## Run the whole suite, including real dotnet build/test runs
	$(BIN)/python -m pytest -q

.PHONY: evaluate
evaluate: ## Run the evaluation benchmark (section 42)
	$(BIN)/python -m tests.evaluation.runner

.PHONY: lint
lint: ## Lint and format-check
	$(BIN)/python -m ruff check .
	$(BIN)/python -m ruff format --check .

.PHONY: format
format: ## Apply formatting
	$(BIN)/python -m ruff format .
	$(BIN)/python -m ruff check --fix .

# ------------------------------------------------------------------ containers

.PHONY: compose-up
compose-up: ## Mode B: build and run everything in Docker
	docker compose up -d --build

.PHONY: compose-scale
compose-scale: ## Mode B with three workers (section 38)
	docker compose up -d --build --scale worker=3

.PHONY: compose-down
compose-down: ## Stop the Docker environment
	docker compose down

.PHONY: compose-logs
compose-logs: ## Follow API and worker logs
	docker compose logs -f api worker

# ----------------------------------------------------------------- kubernetes

.PHONY: k8s-apply
k8s-apply: ## Mode C: apply the Kubernetes manifests
	kubectl apply -f infrastructure/kubernetes/configmap.yaml
	kubectl apply -f infrastructure/kubernetes/secrets.yaml
	kubectl apply -f infrastructure/kubernetes/api-deployment.yaml
	kubectl apply -f infrastructure/kubernetes/worker-deployment.yaml
	kubectl apply -f infrastructure/kubernetes/services.yaml

.PHONY: k8s-delete
k8s-delete: ## Remove the Kubernetes resources
	kubectl delete -f infrastructure/kubernetes/ --ignore-not-found
