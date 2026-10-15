.PHONY: up down migrate seed test lint eval

up:
	docker compose up -d

down:
	docker compose down

migrate:
	alembic upgrade head

seed:
	python -m app.db.seed

test:
	pytest -v

lint:
	ruff check .
	ruff format --check .
	mypy app

eval:
	python -m app.modules.evaluation.cli --provider mock

