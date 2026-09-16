.PHONY: install seed serve run test lint docker-up clean

install:
	pip install -e ".[dev]"

seed:
	python -m meridian seed --data-dir data

serve:
	python -m meridian serve --reload

run:
	python -m meridian run

test:
	pytest -q

lint:
	ruff check src tests

docker-up:
	docker compose up --build

clean:
	rm -rf data/meridian.db
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
