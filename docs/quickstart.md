# Quickstart

## Prerequisites

- Python 3.11+
- Docker (only for the Postgres path)

## 1. Install

```bash
cd meridian
pip install -e ".[dev]"
```

## 2. Start the API

```bash
python -m meridian serve --reload
```

Open http://localhost:8000. The dashboard loads; the API docs are at `/docs`.

The app uses SQLite at `./data/meridian.db` by default and reads the sample catalog from `./data/*.csv` (already in the repo). To regenerate the sample data:

```bash
python -m meridian seed --data-dir data
```

## 3. Run planning

Press **Run planning** in the dashboard, or:

```bash
curl -X POST http://localhost:8000/v1/runs \
  -H 'Content-Type: application/json' -d '{}'
```

With options:

```bash
curl -X POST http://localhost:8000/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"horizon_days": 45, "service_level": 0.98, "requested_by": "ops-team"}'
```

The response is the run summary: orders proposed, spend, POs drafted, SKUs at risk, and a plain-language narrative.

## 4. Approve orders

```bash
# list what needs a human
curl http://localhost:8000/v1/decisions?status=needs_approval

# approve one
curl -X POST http://localhost:8000/v1/decisions/3/approve \
  -H 'Content-Type: application/json' -d '{"decided_by": "ops-team"}'
```

## 5. Docker with Postgres

```bash
docker compose up --build
```

The API waits for Postgres to be healthy, then serves on port 8000. Data persists in the `pgdata` volume.

## 6. Run the tests

```bash
pytest -q
ruff check src tests
```
