"""Regression tests for the audit fixes (P0 + P1 boundaries + P2 quick wins).

Each test names the item it pins so a future regression is traceable.
"""
from __future__ import annotations

import shutil
import threading
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _rebind_session_db(settings):
    """Isolated-catalog tests rebind the global engine; always restore it."""
    from meridian.store.db import init_db

    init_db(settings.database_url)
    yield
    init_db(settings.database_url)


def _linked_po_for_run(client, run_id, need_pending=True):
    """Return (po, decisions) for a PO with at least one needs_approval link."""
    detail = client.get(f"/v1/runs/{run_id}").json()
    decisions = detail["decisions"]
    for po in detail["purchase_orders"]:
        line_skus = {line["sku_id"] for line in po["lines"]}
        linked = [
            d for d in decisions
            if d["sku_id"] in line_skus
            and (d.get("extra") or {}).get("supplier_id", po["supplier_id"])
            == po["supplier_id"]
        ]
        assert linked, "every PO line should have a linked decision"
        if need_pending and not any(
            d["status"] == "needs_approval" for d in linked
        ):
            continue
        return po, linked
    raise AssertionError("no PO with a pending linked decision found")


# --- P0-1: PO approval gate -------------------------------------------------


def test_p0_1_po_approval_rejects_pending_decisions(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    po, linked = _linked_po_for_run(client, run_id)
    pending = [d for d in linked if d["status"] == "needs_approval"]
    assert pending
    r = client.post(
        f"/v1/purchase-orders/{po['id']}/approve", json={"approved_by": "tester"}
    )
    assert r.status_code == 409
    body = r.json()["detail"]
    assert set(body["offending_decision_ids"]) == {d["id"] for d in pending}


def test_p0_1_po_approval_happy_path_records_linkage(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    po, linked = _linked_po_for_run(client, run_id)
    for d in linked:
        if d["status"] == "needs_approval":
            r = client.post(
                f"/v1/decisions/{d['id']}/approve", json={"decided_by": "tester"}
            )
            assert r.status_code == 200
    r = client.post(
        f"/v1/purchase-orders/{po['id']}/approve", json={"approved_by": "tester"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    events = client.get(f"/v1/audit?entity_id={po['id']}").json()
    approvals = [e for e in events if e["action"] == "po.approved"]
    assert approvals
    details = approvals[0]["details"]
    assert set(details["decision_ids"]) == {d["id"] for d in linked}
    assert set(details["decision_statuses"]) == {str(d["id"]) for d in linked}


def test_p0_12_reject_holds_po_and_gate_blocks_on_hold(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    po, linked = _linked_po_for_run(client, run_id)
    target = next(d for d in linked if d["status"] == "needs_approval")
    r = client.post(
        f"/v1/decisions/{target['id']}/reject", json={"decided_by": "tester"}
    )
    assert r.status_code == 200
    held = client.get(f"/v1/purchase-orders/{po['id']}").json()
    assert held["status"] == "on_hold"
    events = client.get(f"/v1/audit?entity_id={po['id']}").json()
    assert any(e["action"] == "po.on_hold" for e in events)
    # on_hold POs enter the gate (not a 404/422): the rejected link blocks them.
    r = client.post(
        f"/v1/purchase-orders/{po['id']}/approve", json={"approved_by": "tester"}
    )
    assert r.status_code == 409
    assert target["id"] in r.json()["detail"]["offending_decision_ids"]


# --- P0-2: negative limits --------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/runs", "/v1/decisions", "/v1/audit"])
@pytest.mark.parametrize("limit", [-1, 0])
def test_p0_2_negative_limit_rejected(client, path, limit):
    r = client.get(f"{path}?limit={limit}")
    assert r.status_code == 422


# --- P0-3: no baked-in credentials ------------------------------------------


def test_p0_3_dockerfile_has_no_credentialed_database_url():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "meridian:meridian@" not in dockerfile
    assert "MERIDIAN_DATABASE_URL=" not in dockerfile


def test_p0_3_compose_reads_password_from_environment():
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "POSTGRES_PASSWORD: meridian" not in compose
    assert "meridian:meridian@" not in compose
    assert "MERIDIAN_DB_PASSWORD:?" in compose


# --- P0-4: auto-approved orders ----------------------------------------------


def test_p0_4_auto_approved_status_and_audit(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    decisions = client.get(f"/v1/decisions?run_id={run_id}").json()
    autos = [d for d in decisions if d["status"] == "auto_approved"]
    assert autos, "sample data should produce below-threshold orders"
    assert all(d["decided_by"] == "policy:auto" for d in autos)
    for d in autos:
        events = client.get(f"/v1/audit?entity_id={d['id']}").json()
        actions = [e for e in events if e["action"] == "decision.auto_approved"]
        assert actions, f"missing decision.auto_approved audit for {d['id']}"
        assert actions[0]["actor"] == "policy"


# --- P0-5: atomic transitions -----------------------------------------------


def test_p0_5_concurrent_approve_race_has_single_winner(client, settings):
    from meridian.store import repository as repo

    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    decisions = client.get(f"/v1/runs/{run_id}").json()["decisions"]
    target = next(d for d in decisions if d["status"] == "needs_approval")
    results = []

    def attempt(status, by):
        results.append(repo.transition_decision_status(target["id"], status, by))

    t1 = threading.Thread(target=attempt, args=("approved", "alice"))
    t2 = threading.Thread(target=attempt, args=("rejected", "bob"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    wins = [r for r in results if isinstance(r, dict)]
    conflicts = [r for r in results if r == "conflict"]
    assert len(wins) == 1
    assert len(conflicts) == 1


def test_p0_5_double_decide_is_conflict(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    decisions = client.get(f"/v1/runs/{run_id}").json()["decisions"]
    target = next(d for d in decisions if d["status"] == "needs_approval")
    assert (
        client.post(
            f"/v1/decisions/{target['id']}/approve", json={"decided_by": "tester"}
        ).status_code
        == 200
    )
    r = client.post(
        f"/v1/decisions/{target['id']}/reject", json={"decided_by": "tester"}
    )
    assert r.status_code == 409
    r = client.post("/v1/decisions/999999/approve", json={"decided_by": "tester"})
    assert r.status_code == 404


# --- P0-6: catalog validation ------------------------------------------------


def _isolated_client(tmp_path, mutate):
    """Fresh app+DB over a copied catalog with one corruption applied."""
    from meridian.api.app import create_app
    from meridian.core.config import Settings
    from meridian.data.generate_sample_data import generate
    from meridian.store.db import init_db

    data_dir = tmp_path / "data"
    generate(str(data_dir))
    mutate(data_dir)
    db_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path}", data_dir=str(data_dir),
        llm_provider="none",
    )
    init_db(settings.database_url)
    return TestClient(create_app(settings))


def _append_row(data_dir, name, row):
    with open(data_dir / name, "a") as f:
        f.write(row + "\n")


def test_p0_6_bad_float_is_422_not_500(tmp_path):
    client = _isolated_client(
        tmp_path, lambda d: _append_row(d, "demand.csv", "SKU-1001,2026-01-01,not-a-number")
    )
    r = client.post("/v1/runs", json={})
    assert r.status_code == 422
    assert r.json()["detail"]["file"] == "demand.csv"


def test_p0_6_unknown_sku_is_422(tmp_path):
    client = _isolated_client(
        tmp_path, lambda d: _append_row(d, "inventory.csv", "SKU-NOPE,WH-01,10,0")
    )
    r = client.post("/v1/runs", json={})
    assert r.status_code == 422
    assert r.json()["detail"]["file"] == "inventory.csv"


def test_p0_6_negative_quantity_is_422(tmp_path):
    client = _isolated_client(
        tmp_path, lambda d: _append_row(d, "demand.csv", "SKU-1001,2026-01-01,-5")
    )
    r = client.post("/v1/runs", json={})
    assert r.status_code == 422


def test_p0_6_failed_run_is_recorded_with_audit(tmp_path):
    client = _isolated_client(
        tmp_path, lambda d: (d / "suppliers.csv").unlink()
    )
    r = client.post("/v1/runs", json={})
    assert r.status_code == 422
    runs = client.get("/v1/runs?limit=10").json()
    failed = [x for x in runs if x["status"] == "failed"]
    assert failed, "load failure must leave a failed run row"
    events = client.get(f"/v1/audit?entity_id={failed[0]['id']}").json()
    assert any(e["action"] == "run.failed" for e in events)


# --- P0-7: whitespace actors -------------------------------------------------


def test_p0_7_whitespace_actor_rejected(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    decisions = client.get(f"/v1/runs/{run_id}").json()["decisions"]
    ids = [d["id"] for d in decisions if d["status"] == "needs_approval"]
    assert len(ids) >= 2
    r = client.post(f"/v1/decisions/{ids[0]}/approve", json={"decided_by": "   "})
    assert r.status_code == 422
    r = client.post(f"/v1/decisions/{ids[1]}/reject", json={"decided_by": "\t\n "})
    assert r.status_code == 422
    # Stripped names are accepted and stored stripped.
    r = client.post(f"/v1/decisions/{ids[0]}/approve", json={"decided_by": "  alice  "})
    assert r.status_code == 200
    assert r.json()["decided_by"] == "alice"


def test_p0_7_whitespace_po_approver_rejected(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    po, _ = _linked_po_for_run(client, run_id, need_pending=False)
    r = client.post(
        f"/v1/purchase-orders/{po['id']}/approve", json={"approved_by": "   "}
    )
    assert r.status_code == 422


def test_p0_7_whitespace_requested_by_rejected(client):
    r = client.post("/v1/runs", json={"requested_by": "   "})
    assert r.status_code == 422


# --- P1 boundaries -----------------------------------------------------------


def test_p1_2_blocked_proposals_persisted_with_audit(client):
    run_id = client.post("/v1/runs", json={}).json()["run_id"]
    blocked = client.get(f"/v1/decisions?run_id={run_id}&status=blocked").json()
    assert blocked, "sample data should produce a blocked proposal"
    for d in blocked:
        assert (d.get("extra") or {}).get("reason")
        events = client.get(f"/v1/audit?entity_id={d['id']}").json()
        assert any(e["action"] == "decision.blocked" for e in events)


def test_p1_3_inputs_hash_covers_bytes(tmp_path):
    from meridian.data.generate_sample_data import generate
    from meridian.data.loader import hash_catalog_files

    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    generate(str(d1))
    shutil.copytree(d1, d2)
    assert hash_catalog_files(str(d1)) == hash_catalog_files(str(d2))
    # Same row counts, different values -> different hash.
    demand = d2 / "demand.csv"
    lines = demand.read_text().splitlines(keepends=True)
    header, rest = lines[0], lines[1:]
    rest[0] = rest[0].split(",")[0] + "," + rest[0].split(",")[1] + ",99999\n"
    demand.write_text(header + "".join(rest))
    assert hash_catalog_files(str(d1)) != hash_catalog_files(str(d2))


def test_p1_4_finish_run_missing_is_noop(settings):
    from meridian.store import repository as repo

    repo.finish_run(run_id="run-does-not-exist", status="failed", summary={})


def test_p1_5_unit_cost_over_cap_blocked_without_po():
    from meridian.agents.base import PlanningContext
    from meridian.agents.procurement import ProcurementAgent
    from meridian.core.config import Settings

    settings = Settings(max_single_po_value=100.0)
    ctx = PlanningContext(
        skus={"SKU-X": {"unit_cost": 500.0, "lead_time_days": 7}},
        suppliers={"SUP-1": {"approved": True, "reliability": 0.9, "name": "S1"}},
        inventory={"SKU-X": {"on_hand": 0, "on_order": 0}},
        demand_history={"SKU-X": [5.0] * 30},
        sku_suppliers={
            "SKU-X": [{"supplier_id": "SUP-1", "unit_cost": 500.0,
                       "lead_time_days": 7, "reliability": 0.9}]
        },
        params={
            "horizon_days": 30,
            "inventory_findings": [
                {"sku_id": "SKU-X", "order_quantity": 2,
                 "days_of_cover_now": 0.0, "forecast_daily_mean": 5.0}
            ],
        },
    )
    result = ProcurementAgent(settings).run(ctx)
    proposals = result.findings[0]["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["status"] == "blocked"
    assert result.findings[0]["purchase_orders"] == []


def test_p1_6_ready_is_static(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "detail": "runbook: run seed + generate + agents"}


def test_p1_7_service_level_floor(client):
    r = client.post("/v1/runs", json={"service_level": 0.85})
    assert r.status_code == 422
    r = client.post("/v1/runs", json={"service_level": 0.90})
    assert r.status_code == 200


def test_p1_8_invalid_log_level_fails_fast():
    import pytest as _pytest
    from pydantic import ValidationError

    from meridian.core.config import Settings

    with _pytest.raises(ValidationError):
        Settings(log_level="VERBOSE-NONSENSE")


def test_p1_9_inventory_covers_all_master_skus(client):
    skus = client.get("/v1/skus").json()
    inv = client.get("/v1/inventory").json()
    assert {r["sku_id"] for r in inv} == {s["sku_id"] for s in skus}


def test_p1_11_metrics_labels_match_real_statuses(client):
    client.post("/v1/runs", json={})
    text = client.get("/metrics").text
    assert 'meridian_decisions_total{status="auto_approved"}' in text
    assert 'meridian_purchase_orders_total{status="on_hold"}' in text
    assert 'status="proposed"}' not in text
    assert 'status="released"}' not in text


def test_p1_11_startup_reconciles_stale_running(settings):
    from meridian.api.app import create_app
    from meridian.store import repository as repo
    from meridian.store.db import init_db

    init_db(settings.database_url)  # bind to the session DB, not a tmp one
    repo.create_run(
        run_id="run-stale-1", params={}, status="running",
        started_at=__import__("datetime").datetime.now(
            __import__("datetime").UTC
        ),
        inputs_hash="",
    )
    create_app(settings)  # startup reconciliation runs here
    assert repo.get_run("run-stale-1")["status"] == "failed"
    events = repo.list_audit_events(entity_id="run-stale-1")
    assert any(e["action"] == "run.failed" for e in events)


def test_p2_7_unknown_status_filter_is_422(client):
    assert client.get("/v1/decisions?status=bogusXYZ").status_code == 422
    assert client.get("/v1/decisions?status=needs-approval").status_code == 422


def test_p2_8_dead_setting_removed():
    from meridian.core.config import Settings

    assert not hasattr(Settings(), "seed_sample_data")
    assert "SEED_SAMPLE_DATA" not in (REPO_ROOT / ".env.example").read_text()
    assert "SEED_SAMPLE_DATA" not in (REPO_ROOT / "docs" / "configuration.md").read_text()


def test_cors_default_deny(client):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_run_summary_counts_are_consistent(client):
    summary = client.post("/v1/runs", json={}).json()
    decisions = client.get(f"/v1/decisions?run_id={summary['run_id']}").json()
    counts = Counter(d["status"] for d in decisions)
    assert (
        summary["orders_proposed"]
        == counts.get("needs_approval", 0) + counts.get("auto_approved", 0)
    )
    assert summary["orders_blocked"] == counts.get("blocked", 0)
