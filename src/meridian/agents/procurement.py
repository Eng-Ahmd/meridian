"""Procurement agent.

Scores candidate suppliers per SKU on cost, reliability, and lead time, picks
the best approved source, and drafts purchase orders grouped by supplier. Drafts
that breach the single-PO cap are split; drafts at or above the approval
threshold are flagged for human approval. Nothing is released without approval.
"""
from __future__ import annotations

import math

from meridian.agents.base import AgentResult, BaseAgent, PlanningContext
from meridian.core.config import Settings
from meridian.core.policy import evaluate_order

# Weights must sum to 1.
W_COST, W_RELIABILITY, W_LEAD_TIME = 0.5, 0.3, 0.2


def score_suppliers(candidates: list[dict]) -> list[dict]:
    """Rank suppliers. Cost and lead time are inverted (lower is better);
    reliability is direct (higher is better). Each factor is min-max normalized
    across the candidate set so the score stays in [0, 1]."""
    if not candidates:
        return []
    costs = [c["unit_cost"] for c in candidates]
    leads = [c["lead_time_days"] for c in candidates]
    rels = [float(c.get("reliability", 0.5)) for c in candidates]

    def norm(value: float, lo: float, hi: float, invert: bool) -> float:
        if hi == lo:
            return 1.0
        n = (value - lo) / (hi - lo)
        return 1.0 - n if invert else n

    ranked = []
    for c in candidates:
        rel = float(c.get("reliability", 0.5))
        score = (
            W_COST * norm(c["unit_cost"], min(costs), max(costs), invert=True)
            + W_RELIABILITY * norm(rel, min(rels), max(rels), invert=False)
            + W_LEAD_TIME * norm(c["lead_time_days"], min(leads), max(leads), invert=True)
        )
        ranked.append({**c, "score": round(score, 4)})
    ranked.sort(key=lambda c: c["score"], reverse=True)
    return ranked


class ProcurementAgent(BaseAgent):
    name = "procurement"
    version = "0.1.0"

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, ctx: PlanningContext) -> AgentResult:
        inventory_findings: list[dict] = ctx.params.get("inventory_findings", [])
        horizon = int(ctx.params.get("horizon_days", 30))
        proposals: list[dict] = []

        for plan in inventory_findings:
            qty = int(plan["order_quantity"])
            if qty <= 0:
                continue
            sku_id = plan["sku_id"]
            candidates = ctx.sku_suppliers.get(sku_id, [])
            ranked = score_suppliers(candidates)
            # Only approved suppliers are eligible for drafting. An unapproved
            # supplier is never silently skipped: if none is approved, the
            # proposal is blocked with the reason recorded.
            approved = [
                c for c in ranked if ctx.suppliers[c["supplier_id"]].get("approved", False)
            ]
            if not approved:
                proposals.append(
                    {
                        "sku_id": sku_id,
                        "quantity": qty,
                        "status": "blocked",
                        "reason": "no approved supplier offers this SKU",
                    }
                )
                continue
            best = approved[0]
            supplier = ctx.suppliers[best["supplier_id"]]
            unit_cost = float(best["unit_cost"])
            if unit_cost > self.settings.max_single_po_value:
                # Even a single unit breaches the cap: no quantity split could
                # ever produce a compliant PO, so block for human review (P1-5).
                proposals.append(
                    {
                        "sku_id": sku_id,
                        "quantity": qty,
                        "supplier_id": best["supplier_id"],
                        "supplier_name": supplier.get("name"),
                        "unit_cost": unit_cost,
                        "total_cost": round(qty * unit_cost, 2),
                        "supplier_score": best["score"],
                        "allowed": False,
                        "needs_approval": False,
                        "policy_reasons": [
                            f"unit cost ${unit_cost:,.2f} exceeds the single-PO cap "
                            f"${self.settings.max_single_po_value:,.2f}; escalated for review"
                        ],
                        "status": "blocked",
                        "reason": (
                            f"unit cost ${unit_cost:,.2f} exceeds the single-PO cap "
                            f"${self.settings.max_single_po_value:,.2f}; escalated for review"
                        ),
                    }
                )
                continue
            verdict = evaluate_order(
                settings=self.settings,
                supplier_approved=bool(supplier.get("approved", False)),
                quantity=qty,
                unit_cost=unit_cost,
                days_of_cover_after_order=float(plan.get("days_of_cover_now") or 0)
                + (qty / max(plan.get("forecast_daily_mean", 1) or 1, 1e-9)),
                planning_horizon_days=horizon,
            )
            proposals.append(
                {
                    "sku_id": sku_id,
                    "quantity": qty,
                    "supplier_id": best["supplier_id"],
                    "supplier_name": supplier.get("name"),
                    "unit_cost": unit_cost,
                    "total_cost": round(qty * unit_cost, 2),
                    "supplier_score": best["score"],
                    "allowed": verdict.allowed,
                    "needs_approval": verdict.needs_approval,
                    "policy_reasons": verdict.reasons,
                    "status": "proposed" if verdict.allowed else "blocked",
                }
            )

        purchase_orders = self._draft_pos(proposals)
        return AgentResult(
            agent=self.name,
            version=self.version,
            findings=[{"proposals": proposals, "purchase_orders": purchase_orders}],
        )

    def _draft_pos(self, proposals: list[dict]) -> list[dict]:
        """Group allowed proposals by supplier; split any PO that would breach
        the single-PO value cap into sequential POs."""
        by_supplier: dict[str, list[dict]] = {}
        for p in proposals:
            if not p.get("allowed"):
                continue
            by_supplier.setdefault(p["supplier_id"], []).append(p)

        pos: list[dict] = []
        for supplier_id, lines in by_supplier.items():
            chunk: list[dict] = []
            chunk_total = 0.0
            for line in lines:
                line_total = line["quantity"] * line["unit_cost"]
                if chunk and chunk_total + line_total > self.settings.max_single_po_value:
                    pos.append(self._make_po(supplier_id, chunk, chunk_total))
                    chunk, chunk_total = [], 0.0
                # A single line over the cap is split into multiple POs by quantity.
                if line_total > self.settings.max_single_po_value:
                    per_po_qty = max(
                        1,
                        int(
                            math.floor(
                                line["quantity"]
                                * self.settings.max_single_po_value
                                / line_total
                            )
                        ),
                    )
                    remaining = line["quantity"]
                    while remaining > 0:
                        q = min(per_po_qty, remaining)
                        split_line = {
                            **line,
                            "quantity": q,
                            "total_cost": round(q * line["unit_cost"], 2),
                        }
                        pos.append(
                            self._make_po(
                                supplier_id,
                                [split_line],
                                q * line["unit_cost"],
                            )
                        )
                        remaining -= q
                else:
                    chunk.append(line)
                    chunk_total += line_total
            if chunk:
                pos.append(self._make_po(supplier_id, chunk, chunk_total))
        return pos

    def _make_po(self, supplier_id: str, lines: list[dict], total: float) -> dict:
        return {
            "supplier_id": supplier_id,
            "lines": [
                {
                    "sku_id": line["sku_id"],
                    "quantity": line["quantity"],
                    "unit_cost": line["unit_cost"],
                    "total_cost": line["total_cost"],
                }
                for line in lines
            ],
            "total_cost": round(total, 2),
            "needs_approval": total >= self.settings.approval_threshold,
            "status": "draft",
        }
