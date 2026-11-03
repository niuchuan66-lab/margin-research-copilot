.PHONY: install dev-api dev-web test lint up down build

install:
	cd frontend && npm install
	cd backend && python -m pip install -e ".[dev]"

dev-api:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-web:
	cd frontend && npm run dev

test:
	cd backend && pytest

lint:
	cd backend && ruff check .
	cd frontend && npm run typecheck

up:
	docker compose up --build

down:
	docker compose down

build:
	cd frontend && npm run build
