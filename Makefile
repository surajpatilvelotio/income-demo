.PHONY: dev fmt lint typecheck install

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --port 8000

fmt:
	uv run ruff format app

lint:
	uv run ruff check app --fix

typecheck:
	uv run pyrefly check app

