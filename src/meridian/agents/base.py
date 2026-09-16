"""Shared agent plumbing: versioned agents operating on a common planning context."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanningContext:
    """Everything an agent may read. Agents never mutate shared state directly;
    they return findings that the orchestrator persists."""

    skus: dict[str, dict[str, Any]]
    suppliers: dict[str, dict[str, Any]]
    inventory: dict[str, dict[str, Any]]
    demand_history: dict[str, list[float]]
    sku_suppliers: dict[str, list[dict[str, Any]]]
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    agent: str
    version: str
    findings: list[dict[str, Any]] = field(default_factory=list)


class BaseAgent:
    name = "base"
    version = "0.1.0"

    def run(self, ctx: PlanningContext) -> AgentResult:
        raise NotImplementedError
