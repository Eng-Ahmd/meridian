"""Repository: the only layer that talks to the database."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select

from meridian.store.db import get_session
from meridian.store.models import AuditEvent, Decision, PurchaseOrder, Run


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
        run.status = status
        run.summary = summary
        run.finished_at = datetime.now(UTC)
        s.commit()


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
    extra: dict | None = None,
) -> int:
    with get_session() as s:
        d = Decision(
            run_id=run_id, agent=agent, sku_id=sku_id, kind=kind, quantity=quantity,
            unit_cost=unit_cost, total_cost=total_cost, rationale=rationale,
            confidence=confidence, status=status, extra=extra or {},
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


def set_decision_status(decision_id: int, status: str, decided_by: str) -> dict | None:
    with get_session() as s:
        d = s.get(Decision, decision_id)
        if d is None:
            return None
        d.status = status
        d.decided_by = decided_by
        d.decided_at = datetime.now(UTC)
        s.commit()
        s.refresh(d)
        return _row_to_dict(d)


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


def approve_purchase_order(po_id: int, approved_by: str) -> dict | None:
    with get_session() as s:
        po = s.get(PurchaseOrder, po_id)
        if po is None:
            return None
        po.status = "approved"
        po.approved_by = approved_by
        po.approved_at = datetime.now(UTC)
        s.commit()
        s.refresh(po)
        return _row_to_dict(po)


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
