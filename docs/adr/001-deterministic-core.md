# ADR 001: Deterministic planning core, LLM at the edge

Date: 2026-09-15
Status: Accepted

## Context

Agentic systems for operations face a trust problem: if the plan changes every time you run it, planners stop trusting it, and auditors cannot reconstruct why an order was placed. LLM-driven planning also fails in ways that are hard to test (a prompt tweak changes outputs silently).

## Decision

Meridian splits the system in two:

1. **Planning core: deterministic.** Forecasting, safety stock, reorder points, supplier scoring, anomaly detection, and policy checks are fixed statistical methods and pure functions. Same inputs produce the same outputs, bit for bit. Every formula is unit-tested against hand-checked values.
2. **LLM at the edge: summaries only.** An optional OpenAI-compatible model rewrites the run summary paragraph for readability. If it is unconfigured, unreachable, or errors, the run completes with a built-in template. The model never sees a decision it can change.

## Consequences

- The system is testable with ordinary unit tests and CI; no LLM-as-judge harness needed for the core.
- Runs are reproducible and auditable: inputs hash plus fixed code equals a reconstructable plan.
- Forecast quality is bounded by the statistical methods (Holt's trend, moving average). Per-SKU model selection and backtesting are future work (see roadmap).
- The narrative summary can vary when the LLM is enabled; it carries no authority and is labeled as such in the dashboard.
