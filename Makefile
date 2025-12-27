.PHONY: dev fmt lint typecheck install docker-up docker-down docker-build docker-logs docker-clean docker-restart docker-backend docker-frontend

# Local development
install:
	uv sync

dev:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

fmt:
	uv run ruff format app

lint:
	uv run ruff check app --fix

typecheck:
	uv run pyrefly check app

# Docker commands - Full Stack (backend + frontend + db)
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

# Docker commands - Backend only (for development)
docker-backend:
	docker-compose up --build -d db backend

docker-backend-logs:
	docker-compose logs -f backend

# Docker commands - Frontend only
docker-frontend:
	docker-compose up --build -d frontend

docker-frontend-logs:
	docker-compose logs -f frontend

# Build individual services
docker-build-backend:
	docker-compose build backend

docker-build-frontend:
	docker-compose build frontend
