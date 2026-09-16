"""Inventory optimization agent.

Computes safety stock, reorder points, and order quantities from the demand
forecast using standard service-level math. All formulas are documented in
docs/agents.md and covered by unit tests with hand-checked values.
"""
from __future__ import annotations

import math

from meridian.agents.base import AgentResult, BaseAgent, PlanningContext
from meridian.agents.forecaster import forecast_demand

# (service level, z-score) anchor points; linear interpolation between them.
_Z_TABLE = [(0.90, 1.28), (0.95, 1.645), (0.98, 2.05), (0.99, 2.33)]


def z_for_service_level(service_level: float) -> float:
    sl = min(0.99, max(0.90, service_level))
    for (x0, z0), (x1, z1) in zip(_Z_TABLE, _Z_TABLE[1:], strict=False):
        if x0 <= sl <= x1:
            if x1 == x0:
                return z0
            return z0 + (z1 - z0) * (sl - x0) / (x1 - x0)
    return _Z_TABLE[-1][1]


def safety_stock(daily_std: float, lead_time_days: float, service_level: float) -> float:
    """SS = z * sigma_d * sqrt(L). Guards against demand variability over lead time."""
    if daily_std <= 0 or lead_time_days <= 0:
        return 0.0
    return z_for_service_level(service_level) * daily_std * math.sqrt(lead_time_days)


def reorder_point(daily_mean: float, lead_time_days: float, ss: float) -> float:
    return daily_mean * lead_time_days + ss


def economic_order_quantity(
    annual_demand: float, order_cost: float, holding_cost_per_unit_year: float
) -> float:
    """EOQ = sqrt(2DS / H). Returns 0 when inputs are degenerate."""
    if annual_demand <= 0 or order_cost <= 0 or holding_cost_per_unit_year <= 0:
        return 0.0
    return math.sqrt(2 * annual_demand * order_cost / holding_cost_per_unit_year)


def plan_replenishment(
    *,
    sku_id: str,
    on_hand: float,
    on_order: float,
    forecast_daily: list[float],
    demand_sigma: float,
    lead_time_days: float,
    review_period_days: int,
    service_level: float,
    min_order_qty: int = 1,
) -> dict:
    cover_days = int(lead_time_days + review_period_days)
    demand_over_cover = float(sum(forecast_daily[:cover_days]))
    daily_mean = float(sum(forecast_daily) / len(forecast_daily)) if forecast_daily else 0.0
    ss = safety_stock(demand_sigma, lead_time_days, service_level)
    rop = reorder_point(daily_mean, lead_time_days, ss)
    target = demand_over_cover + ss
    raw_qty = target - on_hand - on_order
    order_qty = int(math.ceil(max(0.0, raw_qty)))
    if 0 < order_qty < min_order_qty:
        order_qty = min_order_qty
    days_of_cover = (on_hand + on_order) / daily_mean if daily_mean > 0 else float("inf")
    return {
        "sku_id": sku_id,
        "order_quantity": order_qty,
        "safety_stock": round(ss, 2),
        "reorder_point": round(rop, 2),
        "target_stock": round(target, 2),
        "days_of_cover_now": round(days_of_cover, 1) if days_of_cover != float("inf") else None,
        "below_reorder_point": (on_hand + on_order) <= rop,
    }


class InventoryAgent(BaseAgent):
    name = "inventory"
    version = "0.1.0"

    def run(self, ctx: PlanningContext) -> AgentResult:
        horizon = int(ctx.params.get("horizon_days", 30))
        review_days = int(ctx.params.get("review_period_days", 7))
        service_level = float(ctx.params.get("service_level", 0.95))
        findings = []
        for sku_id, series in ctx.demand_history.items():
            fc = forecast_demand(sku_id, series, horizon)
            sku = ctx.skus[sku_id]
            inv = ctx.inventory.get(sku_id, {"on_hand": 0, "on_order": 0})
            plan = plan_replenishment(
                sku_id=sku_id,
                on_hand=float(inv.get("on_hand", 0)),
                on_order=float(inv.get("on_order", 0)),
                forecast_daily=fc.daily,
                demand_sigma=fc.sigma,
                lead_time_days=float(sku.get("lead_time_days", 7)),
                review_period_days=review_days,
                service_level=service_level,
            )
            plan["forecast_total"] = round(fc.total, 2)
            plan["unit_cost"] = float(sku.get("unit_cost", 0.0))
            findings.append(plan)
        return AgentResult(agent=self.name, version=self.version, findings=findings)
