"""Orchestrator: runs the agent pipeline for one planning run and persists results.

Pipeline order is fixed: forecast -> inventory plan -> risk scan -> procurement.
Procurement reads the inventory findings via the shared context params. Every
run, decision, and purchase order is written to the store with an audit trail.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from meridian.agents.base import PlanningContext
from meridian.agents.forecaster import ForecasterAgent
from meridian.agents.inventory import InventoryAgent
from meridian.agents.procurement import ProcurementAgent
from meridian.agents.risk import RiskAgent
from meridian.core.audit import audit_record, inputs_hash
from meridian.core.config import Settings
from meridian.core.logging import get_logger
from meridian.llm.summaries import summarize_run
from meridian.store import repository as repo

log = get_logger("meridian.orchestrator")


def _rationale(p: dict) -> str:
    base = (
        f"Order {p['quantity']} units from {p['supplier_name']} "
        f"(score {p['supplier_score']})."
    )
    if p["policy_reasons"]:
        return base + " " + "; ".join(p["policy_reasons"])
    return base


def run_planning(
    *,
    settings: Settings,
    data: dict[str, Any],
    horizon_days: int | None = None,
    service_level: float | None = None,
    review_period_days: int | None = None,
    requested_by: str = "api",
) -> dict[str, Any]:
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    started = datetime.now(UTC)
    params = {
        "horizon_days": horizon_days or settings.forecast_horizon_days,
        "service_level": service_level or settings.default_service_level,
        "review_period_days": review_period_days or settings.review_period_days,
    }
    log.info("planning run started", extra={"run_id": run_id})

    ctx = PlanningContext(
        skus=data["skus"],
        suppliers=data["suppliers"],
        inventory=data["inventory"],
        demand_history=data["demand_history"],
        sku_suppliers=data["sku_suppliers"],
        params=dict(params),
    )

    first_series = next(iter(data["demand_history"].values()), [])
    run_inputs = {
        "skus": sorted(data["skus"]),
        "params": params,
        "demand_days": len(first_series),
    }
    repo.create_run(
        run_id=run_id,
        params=params,
        status="running",
        started_at=started,
        inputs_hash=inputs_hash(run_inputs),
    )
    repo.add_audit(
        **audit_record(
            actor=requested_by,
            action="run.started",
            entity="run",
            entity_id=run_id,
            details={"params": params},
        )
    )

    try:
        forecast = ForecasterAgent().run(ctx)
        inventory = InventoryAgent().run(ctx)
        ctx.params["inventory_findings"] = inventory.findings
        # expose daily mean for the procurement cover computation
        fc_by_sku = {f["sku_id"]: f for f in forecast.findings}
        for plan in inventory.findings:
            plan["forecast_daily_mean"] = fc_by_sku[plan["sku_id"]]["forecast_daily_mean"]
        risk = RiskAgent().run(ctx)
        procurement = ProcurementAgent(settings).run(ctx)

        proc = procurement.findings[0]
        decision_ids = []
        for p in proc["proposals"]:
            if p["status"] != "proposed":
                continue
            did = repo.add_decision(
                run_id=run_id,
                agent="procurement",
                sku_id=p["sku_id"],
                kind="replenish",
                quantity=p["quantity"],
                unit_cost=p["unit_cost"],
                total_cost=p["total_cost"],
                rationale=_rationale(p),
                confidence=p["supplier_score"],
                status="needs_approval" if p["needs_approval"] else "approved",
                extra={
                    "supplier_id": p["supplier_id"],
                    "policy_reasons": p["policy_reasons"],
                },
            )
            decision_ids.append(did)

        po_ids = []
        for po in proc["purchase_orders"]:
            po_ids.append(
                repo.create_purchase_order(
                    run_id=run_id,
                    supplier_id=po["supplier_id"],
                    lines=po["lines"],
                    total_cost=po["total_cost"],
                    status="draft",
                    needs_approval=po["needs_approval"],
                )
            )

        at_risk = [f["sku_id"] for f in risk.findings if f["stockout_risk"]]
        blocked = [p for p in proc["proposals"] if p["status"] == "blocked"]
        proposed_spend = round(
            sum(p["total_cost"] for p in proc["proposals"] if p["status"] == "proposed"),
            2,
        )
        pos = proc["purchase_orders"]
        summary = {
            "run_id": run_id,
            "params": params,
            "skus_planned": len(ctx.skus),
            "orders_proposed": len(decision_ids),
            "orders_blocked": len(blocked),
            "purchase_orders_drafted": len(po_ids),
            "pos_needing_approval": sum(1 for po in pos if po["needs_approval"]),
            "total_proposed_spend": proposed_spend,
            "skus_at_stockout_risk": at_risk,
            "forecast_methods": sorted({f["method"] for f in forecast.findings}),
        }
        summary["narrative"] = summarize_run(settings, summary)

        repo.finish_run(run_id=run_id, status="succeeded", summary=summary)
        repo.add_audit(
            **audit_record(
                actor="orchestrator",
                action="run.succeeded",
                entity="run",
                entity_id=run_id,
                details={"decisions": len(decision_ids), "purchase_orders": len(po_ids)},
            )
        )
        log.info("planning run succeeded", extra={"run_id": run_id})
        return summary
    except Exception as exc:  # noqa: BLE001 - orchestrator must record failures
        repo.finish_run(run_id=run_id, status="failed", summary={"error": str(exc)})
        repo.add_audit(
            **audit_record(
                actor="orchestrator", action="run.failed", entity="run", entity_id=run_id,
                details={"error": str(exc)},
            )
        )
        log.error("planning run failed: %s", exc, extra={"run_id": run_id})
        raise
