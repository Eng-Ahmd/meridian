"""API routes. All planning endpoints are synchronous and deterministic: a POST to
/v1/runs runs the full agent pipeline and returns the summary in the response."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from meridian.agents.orchestrator import run_planning
from meridian.api.schemas import ApprovalAction, DecisionAction, RunRequest
from meridian.core.audit import audit_record
from meridian.core.config import Settings
from meridian.data.loader import load_data
from meridian.store import repository as repo
from meridian.store.models import Decision, PurchaseOrder, Run

router = APIRouter()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "meridian", "version": "0.1.0"}


@router.get("/ready")
def ready() -> dict:
    try:
        repo.list_runs(limit=1)
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc


@router.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    lines = []
    for status in ("running", "succeeded", "failed"):
        n = repo.count_by(Run, "status", status)
        lines.append(f'meridian_runs_total{{status="{status}"}} {n}')
    for status in ("proposed", "needs_approval", "approved", "rejected", "blocked"):
        n = repo.count_by(Decision, "status", status)
        lines.append(f'meridian_decisions_total{{status="{status}"}} {n}')
    for status in ("draft", "approved", "released"):
        n = repo.count_by(PurchaseOrder, "status", status)
        lines.append(f'meridian_purchase_orders_total{{status="{status}"}} {n}')
    return "\n".join(lines) + "\n"


@router.post("/v1/runs")
def create_run(req: RunRequest, request: Request) -> dict:
    settings = _settings(request)
    data = load_data(settings.data_dir)
    summary = run_planning(
        settings=settings,
        data=data,
        horizon_days=req.horizon_days,
        service_level=req.service_level,
        review_period_days=req.review_period_days,
        requested_by=req.requested_by,
    )
    return summary


@router.get("/v1/runs")
def list_runs(limit: int = Query(default=50, le=200)) -> list[dict]:
    return repo.list_runs(limit=limit)


@router.get("/v1/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    run["decisions"] = repo.list_decisions(run_id=run_id)
    run["purchase_orders"] = repo.list_purchase_orders(run_id=run_id)
    return run


@router.get("/v1/decisions")
def list_decisions(
    run_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, le=500),
) -> list[dict]:
    return repo.list_decisions(run_id=run_id, status=status, limit=limit)


@router.post("/v1/decisions/{decision_id}/approve")
def approve_decision(decision_id: int, action: DecisionAction) -> dict:
    d = repo.get_decision(decision_id)
    if d is None:
        raise HTTPException(status_code=404, detail="decision not found")
    if d["status"] not in ("proposed", "needs_approval"):
        raise HTTPException(status_code=409, detail=f"decision is already {d['status']}")
    updated = repo.set_decision_status(decision_id, "approved", action.decided_by)
    repo.add_audit(
        **audit_record(
            actor=action.decided_by, action="decision.approved", entity="decision",
            entity_id=str(decision_id), details={"note": action.note},
        )
    )
    return updated


@router.post("/v1/decisions/{decision_id}/reject")
def reject_decision(decision_id: int, action: DecisionAction) -> dict:
    d = repo.get_decision(decision_id)
    if d is None:
        raise HTTPException(status_code=404, detail="decision not found")
    if d["status"] not in ("proposed", "needs_approval"):
        raise HTTPException(status_code=409, detail=f"decision is already {d['status']}")
    updated = repo.set_decision_status(decision_id, "rejected", action.decided_by)
    repo.add_audit(
        **audit_record(
            actor=action.decided_by, action="decision.rejected", entity="decision",
            entity_id=str(decision_id), details={"note": action.note},
        )
    )
    return updated


@router.get("/v1/purchase-orders")
def list_purchase_orders(run_id: str | None = None) -> list[dict]:
    return repo.list_purchase_orders(run_id=run_id)


@router.get("/v1/purchase-orders/{po_id}")
def get_purchase_order(po_id: int) -> dict:
    po = repo.get_purchase_order(po_id)
    if po is None:
        raise HTTPException(status_code=404, detail="purchase order not found")
    return po


@router.post("/v1/purchase-orders/{po_id}/approve")
def approve_purchase_order(po_id: int, action: ApprovalAction) -> dict:
    po = repo.get_purchase_order(po_id)
    if po is None:
        raise HTTPException(status_code=404, detail="purchase order not found")
    if po["status"] != "draft":
        raise HTTPException(status_code=409, detail=f"purchase order is already {po['status']}")
    updated = repo.approve_purchase_order(po_id, action.approved_by)
    repo.add_audit(
        **audit_record(
            actor=action.approved_by, action="po.approved", entity="purchase_order",
            entity_id=str(po_id), details={"note": action.note},
        )
    )
    return updated


@router.get("/v1/skus")
def list_skus(request: Request) -> list[dict]:
    return list(load_data(_settings(request).data_dir)["skus"].values())


@router.get("/v1/inventory")
def list_inventory(request: Request) -> list[dict]:
    data = load_data(_settings(request).data_dir)
    out = []
    for sku_id, inv in data["inventory"].items():
        out.append({"sku_id": sku_id, **data["skus"][sku_id], **inv})
    return out


@router.get("/v1/suppliers")
def list_suppliers(request: Request) -> list[dict]:
    return list(load_data(_settings(request).data_dir)["suppliers"].values())


@router.get("/v1/forecast/{sku_id}")
def get_forecast(
    sku_id: str, request: Request, horizon_days: int = Query(default=30, ge=1, le=365)
) -> dict:
    from meridian.agents.forecaster import forecast_demand

    data = load_data(_settings(request).data_dir)
    if sku_id not in data["demand_history"]:
        raise HTTPException(status_code=404, detail="unknown sku")
    fc = forecast_demand(sku_id, data["demand_history"][sku_id], horizon_days)
    return {
        "sku_id": sku_id,
        "method": fc.method,
        "horizon_days": horizon_days,
        "daily": [round(x, 2) for x in fc.daily],
        "total": round(fc.total, 2),
        "sigma": round(fc.sigma, 2),
    }


@router.get("/v1/audit")
def list_audit(entity_id: str | None = None, limit: int = Query(default=200, le=500)) -> list[dict]:
    return repo.list_audit_events(entity_id=entity_id, limit=limit)
