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

- `GET /v1/decisions?status=needs_approval&run_id=...` - filter proposed orders. Unknown `status` values return 422.
- `POST /v1/decisions/{id}/approve` - body `{"decided_by": "name", "note": "..."}`.
- `POST /v1/decisions/{id}/reject` - same body. Rejecting a decision moves every draft PO containing its line to `on_hold` (audit event `po.on_hold`).
- `GET /v1/purchase-orders?run_id=...` - draft POs.
- `GET /v1/purchase-orders/{id}` - PO detail with lines.
- `POST /v1/purchase-orders/{id}/approve` - approve a `draft` or `on_hold` PO. Approval is gated: every decision linked to the PO (same run + SKU, same supplier where recorded) must already be `approved` or `auto_approved`, otherwise 409 listing the offending decision ids.

Approving or rejecting a decision that is already decided returns 409. Every action writes an audit event with the actor and timestamp.

Decision statuses: `needs_approval` (waits for a human), `auto_approved` (below-threshold spend released by policy as `policy:auto`, with a `decision.auto_approved` audit event), `approved`, `rejected`, `blocked` (policy-refused, e.g. unapproved supplier or over-cap order; reason in `extra`, with a `decision.blocked` audit event). PO statuses: `draft`, `on_hold`, `approved`.

## Catalog and forecasts

- `GET /v1/skus` - SKU master.
- `GET /v1/inventory` - on-hand and on-order per SKU (left-joined over the master SKU list; SKUs without an inventory row report zero cover).
- `GET /v1/suppliers` - supplier master with approval status.
- `GET /v1/forecast/{sku_id}?horizon_days=30` - daily forecast, method, and sigma.
- `GET /v1/audit?entity_id=...` - audit trail, newest first.

Malformed catalogs (missing files/columns, bad numbers, negative quantities, dangling supplier/SKU references) return 422 with the offending file and row. A failed `POST /v1/runs` still records the run as `failed` with an audit event.

## Errors

- `400` - invalid request body (validation details in the response).
- `404` - unknown run, decision, PO, or SKU.
- `409` - state conflict (e.g. approving an already-decided order, or a PO whose linked decisions are not all approved).
- `422` - invalid catalog data (file/row included) or unknown `status` filter value.
- `503` - `/ready` when the database is down.
