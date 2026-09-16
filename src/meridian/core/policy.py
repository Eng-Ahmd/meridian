"""Policy guardrails. Every agent-proposed order passes through here before it can
be approved or released. The policy layer is pure functions so it is trivially
testable and auditable."""
from __future__ import annotations

from dataclasses import dataclass, field

from meridian.core.config import Settings


@dataclass
class PolicyVerdict:
    allowed: bool
    needs_approval: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_order(
    *,
    settings: Settings,
    supplier_approved: bool,
    quantity: int,
    unit_cost: float,
    days_of_cover_after_order: float,
    planning_horizon_days: int,
) -> PolicyVerdict:
    """Decide whether a proposed replenishment order may proceed."""
    reasons: list[str] = []
    total = quantity * unit_cost

    if not supplier_approved:
        return PolicyVerdict(
            allowed=False,
            needs_approval=False,
            reasons=["supplier is not on the approved supplier list"],
        )
    if quantity <= 0:
        return PolicyVerdict(
            allowed=False, needs_approval=False, reasons=["order quantity must be positive"]
        )
    if total > settings.max_single_po_value:
        return PolicyVerdict(
            allowed=False,
            needs_approval=False,
            reasons=[
                f"order value ${total:,.2f} exceeds the single-PO cap "
                f"${settings.max_single_po_value:,.2f}; split across multiple POs"
            ],
        )
    if days_of_cover_after_order > planning_horizon_days * 1.5:
        reasons.append(
            "order would cover more than 1.5x the planning horizon; quantity trimmed by planner"
        )

    needs_approval = total >= settings.approval_threshold
    if needs_approval:
        reasons.append(
            f"order value ${total:,.2f} meets the approval threshold "
            f"${settings.approval_threshold:,.2f}; human approval required"
        )
    return PolicyVerdict(allowed=True, needs_approval=needs_approval, reasons=reasons)
