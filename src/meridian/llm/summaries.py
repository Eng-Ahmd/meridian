"""Run summaries. Deterministic template first; LLM rewrite only if configured
and reachable."""
from __future__ import annotations

from meridian.core.config import Settings
from meridian.llm.provider import LlmClient


def _template_summary(summary: dict) -> str:
    p = summary["params"]
    lines = [
        f"Planned {summary['skus_planned']} SKUs over a {p['horizon_days']}-day horizon "
        f"at {p['service_level']:.0%} service level.",
        f"Proposed {summary['orders_proposed']} replenishment orders totaling "
        f"${summary['total_proposed_spend']:,.2f}.",
        f"Drafted {summary['purchase_orders_drafted']} purchase orders; "
        f"{summary['pos_needing_approval']} need human approval.",
    ]
    blocked = summary["orders_blocked"]
    if blocked:
        word = "proposal was" if blocked == 1 else "proposals were"
        lines.append(f"{blocked} {word} blocked by policy.")
    at_risk = summary["skus_at_stockout_risk"]
    if at_risk:
        lines.append(f"Stockout risk on: {', '.join(at_risk)}.")
    else:
        lines.append("No SKUs are at stockout risk.")
    return " ".join(lines)


def summarize_run(settings: Settings, summary: dict) -> str:
    template = _template_summary(summary)
    client = LlmClient(settings)
    if not client.enabled:
        return template
    rewritten = client.complete(
        system=(
            "You write one-paragraph operations summaries for supply chain planners. "
            "Plain language, no jargon, no bullet points. Keep every number from the input."
        ),
        user=f"Rewrite this planning summary in plain language:\n\n{template}",
    )
    return rewritten or template
