"""API routes. All planning endpoints are synchronous and deterministic: a POST to
/v1/runs runs the full agent pipeline and returns the summary in the response."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from meridian.agents.orchestrator import plan_from_catalog
from meridian.api.schemas import ApprovalAction, DecisionAction, RunRequest
from meridian.core.audit import audit_record
from meridian.core.config import Settings
from meridian.core.logging import get_logger
from meridian.data.loader import CatalogError, load_data
from meridian.store import repository as repo
from meridian.store.models import Decision, PurchaseOrder, Run

router = APIRouter()
log = get_logger("meridian.api")

# A PO may be approved only when every linked decision is in one of these.
# "auto_approved" counts: policy already released that spend with an audit event.
APPROVED_DECISION_STATUSES = ("approved", "auto_approved")

# Every status a decision row can ever hold. Anything else is a caller typo.
KNOWN_DECISION_STATUSES = frozenset(
    {"proposed", "needs_approval", "approved", "auto_approved", "rejected", "blocked"}
)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _catalog_error(exc: CatalogError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"file": exc.file, "row": exc.row, "message": exc.message},
    )


def _linked_decisions(po: dict) -> list[dict]:
    """Decisions linked to a PO: same run, SKU in the PO lines, and same
    supplier where a supplier is recorded on both sides."""
    line_skus = {
        line.get("sku_id") for line in (po.get("lines") or []) if line.get("sku_id")
    }
    if not line_skus:
        return []
    linked = []
    for d in repo.list_decisions(run_id=po["run_id"], limit=100_000):
        if d["sku_id"] not in line_skus:
            continue
        d_supplier = (d.get("extra") or {}).get("supplier_id")
        if (
            d_supplier
            and po.get("supplier_id")
            and d_supplier != po["supplier_id"]
        ):
            continue
        linked.append(d)
    return linked


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "meridian", "version": "0.1.0"}


@router.get("/ready")
def ready() -> dict:
    # Static on purpose (P1-6): readiness reports the recovery runbook without
    # touching the database, so no driver error text (or credentials) can leak.
    return {"status": "ready", "detail": "runbook: run seed + generate + agents"}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    lines = []
    for status in ("running", "succeeded", "failed"):
        n = repo.count_by(Run, "status", status)
        lines.append(f'meridian_runs_total{{status="{status}"}} {n}')
    for status in ("needs_approval", "approved", "auto_approved", "rejected", "blocked"):
        n = repo.count_by(Decision, "status", status)
        lines.append(f'meridian_decisions_total{{status="{status}"}} {n}')
    for status in ("draft", "on_hold", "approved"):
        n = repo.count_by(PurchaseOrder, "status", status)
        lines.append(f'meridian_purchase_orders_total{{status="{status}"}} {n}')
    return "\n".join(lines) + "\n"


@router.post("/v1/runs")
def create_run(req: RunRequest, request: Request) -> dict:
    settings = _settings(request)
    try:
        return plan_from_catalog(
            settings=settings,
            data_dir=settings.data_dir,
            horizon_days=req.horizon_days,
            service_level=req.service_level,
            review_period_days=req.review_period_days,
            requested_by=req.requested_by,
        )
    except CatalogError as exc:
        raise _catalog_error(exc) from exc


@router.get("/v1/runs")
def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
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
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict]:
    if status is not None and status not in KNOWN_DECISION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status {status!r}; known: {sorted(KNOWN_DECISION_STATUSES)}",
        )
    return repo.list_decisions(run_id=run_id, status=status, limit=limit)


@router.post("/v1/decisions/{decision_id}/approve")
def approve_decision(decision_id: int, action: DecisionAction) -> dict:
    updated = repo.transition_decision_status(decision_id, "approved", action.decided_by)
    if updated == "missing":
        raise HTTPException(status_code=404, detail="decision not found")
    if updated == "conflict":
        current = repo.get_decision(decision_id)
        raise HTTPException(
            status_code=409, detail=f"decision is already {current['status']}"
        )
    repo.add_audit(
        **audit_record(
            actor=action.decided_by, action="decision.approved", entity="decision",
            entity_id=str(decision_id), details={"note": action.note},
        )
    )
    return updated


@router.post("/v1/decisions/{decision_id}/reject")
def reject_decision(decision_id: int, action: DecisionAction) -> dict:
    updated = repo.transition_decision_status(decision_id, "rejected", action.decided_by)
    if updated == "missing":
        raise HTTPException(status_code=404, detail="decision not found")
    if updated == "conflict":
        current = repo.get_decision(decision_id)
        raise HTTPException(
            status_code=409, detail=f"decision is already {current['status']}"
        )
    repo.add_audit(
        **audit_record(
            actor=action.decided_by, action="decision.rejected", entity="decision",
            entity_id=str(decision_id), details={"note": action.note},
        )
    )
    # P0-12: a rejected line holds every draft PO containing it.
    held = repo.hold_purchase_orders_for_decision(
        run_id=updated["run_id"], sku_id=updated["sku_id"]
    )
    for po in held:
        repo.add_audit(
            **audit_record(
                actor=action.decided_by, action="po.on_hold", entity="purchase_order",
                entity_id=str(po["id"]),
                details={
                    "reason": "linked decision rejected",
                    "decision_id": decision_id,
                    "sku_id": updated["sku_id"],
                },
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
    if po["status"] not in ("draft", "on_hold"):
        raise HTTPException(
            status_code=409, detail=f"purchase order is already {po['status']}"
        )
    # P0-1 gate: every linked decision must already be human- or policy-approved.
    linked = _linked_decisions(po)
    offenders = [d for d in linked if d["status"] not in APPROVED_DECISION_STATUSES]
    if offenders:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "purchase order has decisions pending approval",
                "offending_decision_ids": [d["id"] for d in offenders],
                "offending_statuses": {str(d["id"]): d["status"] for d in offenders},
            },
        )
    updated = repo.transition_purchase_order_status(po_id, "approved", action.approved_by)
    if updated == "missing":  # pragma: no cover - row existed a moment ago
        raise HTTPException(status_code=404, detail="purchase order not found")
    if updated == "conflict":
        current = repo.get_purchase_order(po_id)
        raise HTTPException(
            status_code=409, detail=f"purchase order is already {current['status']}"
        )
    repo.add_audit(
        **audit_record(
            actor=action.approved_by, action="po.approved", entity="purchase_order",
            entity_id=str(po_id),
            details={
                "note": action.note,
                "decision_ids": [d["id"] for d in linked],
                "decision_statuses": {str(d["id"]): d["status"] for d in linked},
            },
        )
    )
    return updated


@router.get("/v1/skus")
def list_skus(request: Request) -> list[dict]:
    try:
        return list(load_data(_settings(request).data_dir)["skus"].values())
    except CatalogError as exc:
        raise _catalog_error(exc) from exc


@router.get("/v1/inventory")
def list_inventory(request: Request) -> list[dict]:
    try:
        data = load_data(_settings(request).data_dir)
    except CatalogError as exc:
        raise _catalog_error(exc) from exc
    # LEFT JOIN over the master SKU list (P1-9): SKUs without an inventory row
    # report zero cover instead of vanishing. Dangling inventory rows never
    # reach here — the catalog validator rejects them with 422.
    out = []
    for sku_id, sku in data["skus"].items():
        inv = data["inventory"].get(
            sku_id, {"location": None, "on_hand": 0, "on_order": 0}
        )
        out.append({"sku_id": sku_id, **sku, **inv})
    return out


@router.get("/v1/suppliers")
def list_suppliers(request: Request) -> list[dict]:
    try:
        return list(load_data(_settings(request).data_dir)["suppliers"].values())
    except CatalogError as exc:
        raise _catalog_error(exc) from exc


@router.get("/v1/forecast/{sku_id}")
def get_forecast(
    sku_id: str, request: Request, horizon_days: int = Query(default=30, ge=1, le=365)
) -> dict:
    from meridian.agents.forecaster import forecast_demand

    try:
        data = load_data(_settings(request).data_dir)
    except CatalogError as exc:
        raise _catalog_error(exc) from exc
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
def list_audit(
    entity_id: str | None = None, limit: int = Query(default=200, ge=1, le=500)
) -> list[dict]:
    return repo.list_audit_events(entity_id=entity_id, limit=limit)
