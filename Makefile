.PHONY: bootstrap dev lint test test-int eval-smoke eval-full synth deploy destroy

ENV ?= dev
CELL ?= a

bootstrap:
	uv sync --all-packages --locked
	pnpm install --frozen-lockfile
	uv run pre-commit install
	docker compose up -d --build --wait

dev:
	pnpm --filter @verimed/web dev --hostname 127.0.0.1

test-int:
	uv run --all-packages python services/api/test_integration.py --env $(ENV) --cell $(CELL)

eval-smoke:
	@echo "not implemented until Phase 3"
	@exit 1

eval-full:
	@echo "not implemented until Phase 6"
	@exit 1

lint:
	pnpm exec eslint . --max-warnings 0
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy spikes
	uv run --all-packages mypy services/api
	uv run --all-packages mypy services/cks
	uv run --all-packages mypy services/simulator
	pnpm exec prettier --check .

test:
	uv run --all-packages pytest
	pnpm --filter @verimed/cdk test

synth:
	pnpm --filter @verimed/cdk exec cdk synth HubFoundation CellFoundation

deploy:
	pnpm --filter @verimed/cdk exec cdk deploy HubFoundation CellFoundation -c env=$(ENV) -c cell=$(CELL)

destroy:
	pnpm --filter @verimed/cdk exec cdk destroy CellFoundation -c env=$(ENV) -c cell=$(CELL)
