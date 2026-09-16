"""Demand forecasting agent.

Deterministic statistical forecasting. Holt's linear trend method for SKUs with
enough history, moving average for sparse histories. No LLM is involved, so
forecasts are reproducible bit-for-bit from the same inputs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from meridian.agents.base import AgentResult, BaseAgent, PlanningContext


@dataclass
class Forecast:
    sku_id: str
    horizon_days: int
    daily: list[float]
    total: float
    sigma: float
    method: str

    @property
    def daily_mean(self) -> float:
        return self.total / self.horizon_days if self.horizon_days else 0.0


def holt_forecast(
    series: list[float], horizon: int, alpha: float = 0.3, beta: float = 0.1
) -> list[float]:
    level = float(series[0])
    trend = float(series[1] - series[0]) if len(series) > 1 else 0.0
    for i in range(1, len(series)):
        prev_level = level
        level = alpha * float(series[i]) + (1.0 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1.0 - beta) * trend
    return [max(0.0, level + (h + 1) * trend) for h in range(horizon)]


def moving_average_forecast(series: list[float], horizon: int, window: int = 14) -> list[float]:
    window = min(window, len(series))
    avg = float(sum(series[-window:]) / window)
    return [max(0.0, avg)] * horizon


def forecast_demand(sku_id: str, series: list[float], horizon_days: int) -> Forecast:
    values = [max(0.0, float(x)) for x in series]
    if len(values) >= 28:
        daily = holt_forecast(values, horizon_days)
        method = "holt-linear-trend"
    elif values:
        daily = moving_average_forecast(values, horizon_days)
        method = "moving-average"
    else:
        daily = [0.0] * horizon_days
        method = "no-history"
    sigma = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return Forecast(
        sku_id=sku_id,
        horizon_days=horizon_days,
        daily=daily,
        total=float(sum(daily)),
        sigma=sigma,
        method=method,
    )


class ForecasterAgent(BaseAgent):
    name = "forecaster"
    version = "0.1.0"

    def run(self, ctx: PlanningContext) -> AgentResult:
        horizon = int(ctx.params.get("horizon_days", 30))
        findings = []
        for sku_id, series in ctx.demand_history.items():
            fc = forecast_demand(sku_id, series, horizon)
            findings.append(
                {
                    "sku_id": sku_id,
                    "method": fc.method,
                    "horizon_days": horizon,
                    "forecast_total": round(fc.total, 2),
                    "forecast_daily_mean": round(fc.daily_mean, 2),
                    "demand_sigma": round(fc.sigma, 2),
                }
            )
        return AgentResult(agent=self.name, version=self.version, findings=findings)
