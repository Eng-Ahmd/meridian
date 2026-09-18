"""Repository: the only layer that talks to the database."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import desc, select, update

from meridian.store.db import get_session
from meridian.store.models import AuditEvent, Decision, PurchaseOrder, Run

# Terminal-ish states a human decision may leave. Only rows still in one of
# these states may be transitioned; anything else is a 409 conflict.
PENDING_DECISION_STATUSES = ("proposed", "needs_approval")

# PO statuses that may still be approved. "on_hold" POs re-enter the gate after
# a linked rejection is resolved by a fresh planning run.
APPROVABLE_PO_STATUSES = ("draft", "on_hold")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def create_run(
    *, run_id: str, params: dict, status: str, started_at: datetime, inputs_hash: str
) -> None:
    with get_session() as s:
        s.add(
            Run(
                id=run_id,
                params=params,
                status=status,
                started_at=started_at,
                inputs_hash=inputs_hash,
            )
        )
        s.commit()


def finish_run(*, run_id: str, status: str, summary: dict) -> None:
    with get_session() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        run.status = status
        run.summary = summary
        run.finished_at = datetime.now(UTC)
        s.commit()


def set_run_inputs_hash(*, run_id: str, inputs_hash: str) -> None:
    with get_session() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        run.inputs_hash = inputs_hash
        s.commit()


def list_running_run_ids() -> list[str]:
    """Ids of runs left in 'running' by a previous process (startup reconcile)."""
    with get_session() as s:
        rows = s.execute(select(Run.id).where(Run.status == "running")).all()
        return [r[0] for r in rows]


def get_run(run_id: str) -> dict | None:
    with get_session() as s:
        run = s.get(Run, run_id)
        return _row_to_dict(run) if run else None


def list_runs(limit: int = 50) -> list[dict]:
    with get_session() as s:
        rows = s.execute(select(Run).order_by(desc(Run.started_at)).limit(limit)).scalars().all()
        return [_row_to_dict(r) for r in rows]


def add_decision(
    *,
    run_id: str,
    agent: str,
    sku_id: str,
    kind: str,
    quantity: int,
    unit_cost: float,
    total_cost: float,
    rationale: str,
    confidence: float,
    status: str,
    decided_by: str | None = None,
    extra: dict | None = None,
) -> int:
    with get_session() as s:
        d = Decision(
            run_id=run_id, agent=agent, sku_id=sku_id, kind=kind, quantity=quantity,
            unit_cost=unit_cost, total_cost=total_cost, rationale=rationale,
            confidence=confidence, status=status, decided_by=decided_by,
            decided_at=datetime.now(UTC) if decided_by is not None else None,
            extra=extra or {},
        )
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id


def get_decision(decision_id: int) -> dict | None:
    with get_session() as s:
        d = s.get(Decision, decision_id)
        return _row_to_dict(d) if d else None


def list_decisions(
    *, run_id: str | None = None, status: str | None = None, limit: int = 200
) -> list[dict]:
    with get_session() as s:
        q = select(Decision).order_by(desc(Decision.id)).limit(limit)
        if run_id:
            q = q.where(Decision.run_id == run_id)
        if status:
            q = q.where(Decision.status == status)
        return [_row_to_dict(d) for d in s.execute(q).scalars().all()]


TransitionResult = Literal["missing", "conflict"]


def transition_decision_status(
    decision_id: int, status: str, decided_by: str
) -> dict | TransitionResult:
    """Atomically move a pending decision to its new status.

    Single UPDATE guarded by the pending-status predicate, so two concurrent
    callers cannot both succeed: exactly one wins the row, the loser sees
    rowcount 0 and gets "missing" (no such row) or "conflict" (already decided).
    """
    with get_session() as s:
        res = s.execute(
            update(Decision)
            .where(
                Decision.id == decision_id,
                Decision.status.in_(PENDING_DECISION_STATUSES),
            )
            .values(
                status=status, decided_by=decided_by, decided_at=datetime.now(UTC)
            )
        )
        s.commit()
        if res.rowcount:
            d = s.get(Decision, decision_id)
            return _row_to_dict(d)
        exists = (
            s.execute(
                select(Decision.id).where(Decision.id == decision_id)
            ).first()
            is not None
        )
        return "missing" if not exists else "conflict"


def create_purchase_order(
    *,
    run_id: str,
    supplier_id: str,
    lines: list,
    total_cost: float,
    status: str,
    needs_approval: bool,
) -> int:
    with get_session() as s:
        po = PurchaseOrder(
            run_id=run_id, supplier_id=supplier_id, lines=lines,
            total_cost=total_cost, status=status, needs_approval=needs_approval,
        )
        s.add(po)
        s.commit()
        s.refresh(po)
        return po.id


def list_purchase_orders(*, run_id: str | None = None, limit: int = 200) -> list[dict]:
    with get_session() as s:
        q = select(PurchaseOrder).order_by(desc(PurchaseOrder.id)).limit(limit)
        if run_id:
            q = q.where(PurchaseOrder.run_id == run_id)
        return [_row_to_dict(p) for p in s.execute(q).scalars().all()]


def get_purchase_order(po_id: int) -> dict | None:
    with get_session() as s:
        po = s.get(PurchaseOrder, po_id)
        return _row_to_dict(po) if po else None


def transition_purchase_order_status(
    po_id: int, status: str, approved_by: str
) -> dict | TransitionResult:
    """Atomically move a draft/on_hold PO to its new status (same race safety
    as decision transitions)."""
    with get_session() as s:
        res = s.execute(
            update(PurchaseOrder)
            .where(
                PurchaseOrder.id == po_id,
                PurchaseOrder.status.in_(APPROVABLE_PO_STATUSES),
            )
            .values(
                status=status, approved_by=approved_by, approved_at=datetime.now(UTC)
            )
        )
        s.commit()
        if res.rowcount:
            po = s.get(PurchaseOrder, po_id)
            return _row_to_dict(po)
        exists = (
            s.execute(
                select(PurchaseOrder.id).where(PurchaseOrder.id == po_id)
            ).first()
            is not None
        )
        return "missing" if not exists else "conflict"


def hold_purchase_orders_for_decision(*, run_id: str, sku_id: str) -> list[dict]:
    """Move every *draft* PO of this run that contains the SKU line to on_hold.

    Already-approved POs are never touched (money already released); already
    on_hold POs stay as-is. Returns the POs that actually transitioned.
    """
    transitioned: list[dict] = []
    with get_session() as s:
        pos = s.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.run_id == run_id,
                PurchaseOrder.status == "draft",
            )
        ).scalars().all()
        for po in pos:
            lines = po.lines or []
            if not any(line.get("sku_id") == sku_id for line in lines):
                continue
            res = s.execute(
                update(PurchaseOrder)
                .where(
                    PurchaseOrder.id == po.id,
                    PurchaseOrder.status == "draft",
                )
                .values(status="on_hold")
            )
            if res.rowcount:
                s.refresh(po)
                transitioned.append(_row_to_dict(po))
        s.commit()
        return transitioned


def add_audit(
    *, actor: str, action: str, entity: str, entity_id: str, details: dict | None = None
) -> None:
    with get_session() as s:
        s.add(
            AuditEvent(
                actor=actor,
                action=action,
                entity=entity,
                entity_id=entity_id,
                details=details or {},
            )
        )
        s.commit()


def list_audit_events(*, entity_id: str | None = None, limit: int = 200) -> list[dict]:
    with get_session() as s:
        q = select(AuditEvent).order_by(desc(AuditEvent.ts)).limit(limit)
        if entity_id:
            q = q.where(AuditEvent.entity_id == entity_id)
        return [_row_to_dict(e) for e in s.execute(q).scalars().all()]


def count_by(table, column: str, value: str) -> int:
    from sqlalchemy import func

    with get_session() as s:
        return s.execute(
            select(func.count()).select_from(table).where(getattr(table, column) == value)
        ).scalar_one()
