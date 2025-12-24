.PHONY: dev fmt lint typecheck install docker-up docker-down docker-build docker-logs docker-clean docker-restart

# Local development
install:
	uv sync

dev:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

fmt:
	uv run ruff format app

lint:
	uv run ruff check app --fix

typecheck:
	uv run pyrefly check app

# Docker commands
docker-build:
	docker-compose build

docker-up:
	docker-compose up --build -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-clean:
	docker-compose down -v --rmi local

docker-restart:
	docker-compose down
	docker-compose up --build -d

