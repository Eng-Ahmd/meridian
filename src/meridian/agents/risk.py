"""Risk agent.

Scans demand history for anomalies (rolling z-score spikes and drops) and
flags SKUs whose days of cover fall below supplier lead time. Findings feed the
run summary so planners see risk next to the proposed orders.
"""
from __future__ import annotations

import numpy as np

from meridian.agents.base import AgentResult, BaseAgent, PlanningContext


def demand_anomalies(
    series: list[float], window: int = 28, threshold: float = 3.0
) -> list[dict]:
    """Points whose deviation from the trailing window mean exceeds `threshold`
    standard deviations. Returns the most recent anomaly per direction at most,
    plus a count, to keep findings compact."""
    values = np.asarray(series, dtype=float)
    out: list[dict] = []
    if len(values) < window + 1:
        return out
    for i in range(window, len(values)):
        window_vals = values[i - window : i]
        mu = float(window_vals.mean())
        sigma = float(window_vals.std(ddof=1))
        if sigma == 0:
            continue
        z = (float(values[i]) - mu) / sigma
        if abs(z) >= threshold:
            out.append(
                {
                    "index": i,
                    "value": round(float(values[i]), 2),
                    "window_mean": round(mu, 2),
                    "z_score": round(z, 2),
                    "direction": "spike" if z > 0 else "drop",
                }
            )
    return out


def days_of_cover(on_hand: float, on_order: float, daily_mean: float) -> float | None:
    if daily_mean <= 0:
        return None
    return (on_hand + on_order) / daily_mean


class RiskAgent(BaseAgent):
    name = "risk"
    version = "0.1.0"

    def run(self, ctx: PlanningContext) -> AgentResult:
        findings = []
        for sku_id, series in ctx.demand_history.items():
            anomalies = demand_anomalies(series)
            sku = ctx.skus[sku_id]
            inv = ctx.inventory.get(sku_id, {"on_hand": 0, "on_order": 0})
            daily_mean = float(np.mean(series)) if series else 0.0
            cover = days_of_cover(
                float(inv.get("on_hand", 0)), float(inv.get("on_order", 0)), daily_mean
            )
            lead_time = float(sku.get("lead_time_days", 7))
            findings.append(
                {
                    "sku_id": sku_id,
                    "anomaly_count": len(anomalies),
                    "recent_anomalies": anomalies[-3:],
                    "days_of_cover": round(cover, 1) if cover is not None else None,
                    "lead_time_days": lead_time,
                    "stockout_risk": bool(cover is not None and cover < lead_time),
                }
            )
        return AgentResult(agent=self.name, version=self.version, findings=findings)
