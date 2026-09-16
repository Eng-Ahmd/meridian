# Agents

Each agent is a versioned, deterministic unit. `BaseAgent.run(ctx)` takes a `PlanningContext` and returns an `AgentResult` with findings. Agents never touch the database or the network.

## Forecaster (`agents/forecaster.py`)

Predicts daily demand per SKU for the planning horizon.

- 28+ days of history: Holt's linear trend (level + trend smoothing, alpha 0.3, beta 0.1).
- Shorter history: 14-day moving average.
- No history: zeros, flagged with method `no-history`.

Output per SKU: method used, forecast total, daily mean, and sigma (residual standard deviation of history), which feeds safety stock math. The method is recorded per SKU so planners can see which forecasts rest on thin data.

## Inventory (`agents/inventory.py`)

Turns forecasts into order quantities.

- Safety stock: `SS = z * sigma_d * sqrt(L)`, where `z` comes from the target service level (interpolated from standard normal anchors at 90/95/98/99%).
- Reorder point: `ROP = daily_mean * L + SS`.
- Order quantity: covers lead time plus review period, plus safety stock, minus on-hand and on-order, rounded up and floored at the SKU minimum order quantity.

Also computes EOQ (`sqrt(2DS/H)`) as a reference quantity; it is reported, not enforced, because real order constraints (MOQs, pack sizes, budgets) vary by site.

## Risk (`agents/risk.py`)

Two checks per SKU:

1. **Demand anomalies.** Rolling 28-day z-score; points beyond 3 sigma are flagged as spikes or drops with their z-score and window mean.
2. **Stockout risk.** Days of cover (on-hand plus on-order over daily mean) below supplier lead time.

Findings land in the run summary so risk is visible next to the proposed orders.

## Procurement (`agents/procurement.py`)

Scores candidate suppliers per SKU on unit cost (50%), reliability (30%), and lead time (20%), each min-max normalized across the candidates. Only approved suppliers are eligible: the best approved source wins, and if no approved supplier offers a SKU the proposal is blocked with the reason recorded. The policy layer still re-checks approval as a backstop against stale data.

Draft purchase orders group lines by supplier. A PO that would exceed the single-PO cap is split into sequential POs; a single line over the cap is split by quantity. POs at or above the approval threshold are flagged `needs_approval`.

## Orchestrator (`agents/orchestrator.py`)

Runs the pipeline in the fixed order forecast, inventory, risk, procurement. It writes the run row, each decision (with rationale, policy verdict, and confidence), draft POs, and audit events. On failure it marks the run `failed` with the error and re-raises.

## Adding an agent

1. Subclass `BaseAgent` in `agents/`, set `name` and `version`.
2. Read from `ctx`; return findings as plain dicts.
3. Wire it into `run_planning` in the order it should execute.
4. Add unit tests in `tests/` and document the method here.
