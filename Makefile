.PHONY: bootstrap dev lint test test-int eval-smoke eval-full synth deploy destroy

ENV ?= dev
CELL ?= a

bootstrap:
	uv sync --all-packages --locked
	pnpm install --frozen-lockfile
	uv run pre-commit install
	docker compose up -d --build --wait

dev test-int:
	@echo "not implemented until Phase 1"
	@exit 1

eval-smoke:
	@echo "not implemented until Phase 3"
	@exit 1

eval-full:
	@echo "not implemented until Phase 6"
	@exit 1

lint:
	pnpm exec eslint .
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy spikes
	pnpm exec prettier --check .

test:
	pnpm --filter @verimed/cdk test

synth:
	pnpm --filter @verimed/cdk exec cdk synth HubFoundation CellFoundation

deploy:
	pnpm --filter @verimed/cdk exec cdk deploy HubFoundation CellFoundation -c env=$(ENV) -c cell=$(CELL)

destroy:
	pnpm --filter @verimed/cdk exec cdk destroy CellFoundation -c env=$(ENV) -c cell=$(CELL)
