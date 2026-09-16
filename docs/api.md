# API reference

Base URL: `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`.

## Operations

- `GET /health` - liveness. Returns `{"status": "ok", ...}`.
- `GET /ready` - readiness. 503 if the database is unreachable.
- `GET /metrics` - Prometheus-formatted counters for runs, decisions, and purchase orders by status.

## Planning runs

- `POST /v1/runs` - execute a planning run. Body (all optional):

```json
{
  "horizon_days": 30,
  "service_level": 0.95,
  "review_period_days": 7,
  "requested_by": "ops-team"
}
```

Returns the run summary: orders proposed, blocked counts, POs drafted, total proposed spend, SKUs at stockout risk, forecast methods used, and the narrative paragraph.

- `GET /v1/runs?limit=50` - run history, newest first.
- `GET /v1/runs/{run_id}` - run detail including its decisions and purchase orders.

## Human-in-the-loop

- `GET /v1/decisions?status=needs_approval&run_id=...` - filter proposed orders.
- `POST /v1/decisions/{id}/approve` - body `{"decided_by": "name", "note": "..."}`.
- `POST /v1/decisions/{id}/reject` - same body.
- `GET /v1/purchase-orders?run_id=...` - draft POs.
- `GET /v1/purchase-orders/{id}` - PO detail with lines.
- `POST /v1/purchase-orders/{id}/approve` - approve a draft PO.

Approving or rejecting a decision that is already decided returns 409. Every action writes an audit event with the actor and timestamp.

## Catalog and forecasts

- `GET /v1/skus` - SKU master.
- `GET /v1/inventory` - on-hand and on-order per SKU.
- `GET /v1/suppliers` - supplier master with approval status.
- `GET /v1/forecast/{sku_id}?horizon_days=30` - daily forecast, method, and sigma.
- `GET /v1/audit?entity_id=...` - audit trail, newest first.

## Errors

- `400` - invalid request body (validation details in the response).
- `404` - unknown run, decision, PO, or SKU.
- `409` - state conflict (e.g. approving an already-decided order).
- `503` - `/ready` when the database is down.
