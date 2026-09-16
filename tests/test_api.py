"""API integration tests: full planning run and the human-in-the-loop flow."""


def test_health_and_ready(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_planning_run_end_to_end(client):
    resp = client.post("/v1/runs", json={})
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["skus_planned"] == 12
    assert summary["orders_proposed"] > 0
    assert "narrative" in summary and summary["narrative"]

    run_id = summary["run_id"]
    detail = client.get(f"/v1/runs/{run_id}").json()
    assert detail["status"] == "succeeded"
    assert len(detail["decisions"]) == summary["orders_proposed"]
    assert len(detail["purchase_orders"]) == summary["purchase_orders_drafted"]


def test_approve_reject_flow(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    decisions = client.get(f"/v1/runs/{run_id}").json()["decisions"]
    assert len(decisions) >= 2

    first, second = decisions[0]["id"], decisions[1]["id"]

    r = client.post(f"/v1/decisions/{first}/approve", json={"decided_by": "tester"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["decided_by"] == "tester"

    # Double-decide is a conflict.
    r = client.post(f"/v1/decisions/{first}/approve", json={"decided_by": "tester"})
    assert r.status_code == 409

    r = client.post(f"/v1/decisions/{second}/reject", json={"decided_by": "tester"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    # Unknown decision.
    r = client.post("/v1/decisions/999999/approve", json={"decided_by": "tester"})
    assert r.status_code == 404


def test_purchase_order_approval(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    pos = client.get(f"/v1/purchase-orders?run_id={run_id}").json()
    assert pos, "expected draft purchase orders"
    po_id = pos[0]["id"]
    r = client.post(f"/v1/purchase-orders/{po_id}/approve", json={"approved_by": "tester"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_forecast_endpoint(client):
    r = client.get("/v1/forecast/SKU-1001?horizon_days=30")
    assert r.status_code == 200
    body = r.json()
    assert len(body["daily"]) == 30
    assert body["method"] in ("holt-linear-trend", "moving-average", "no-history")

    r = client.get("/v1/forecast/NOPE")
    assert r.status_code == 404


def test_audit_trail_records_run(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    events = client.get(f"/v1/audit?entity_id={run_id}").json()
    actions = {e["action"] for e in events}
    assert "run.started" in actions
    assert "run.succeeded" in actions


def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "meridian_runs_total" in r.text
