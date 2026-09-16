# Evaluation

Because the planning core is deterministic, it can be tested like any other numerical code. There is no "vibes-based" grading here.

## Unit tests (`tests/`)

- `test_forecaster.py` - Holt's method recovers a linear trend; short histories fall back to moving average; empty history yields zeros.
- `test_inventory.py` - safety stock, reorder point, and EOQ against hand-computed values; order quantity respects MOQ and never goes negative.
- `test_policy.py` - unapproved suppliers blocked; over-cap orders blocked; threshold orders flagged for approval; below-threshold orders pass clean.
- `test_risk.py` - injected spikes and drops are detected with the right direction; quiet series produce no findings.
- `test_api.py` - end-to-end through the HTTP layer: run planning, list decisions, approve and reject, 409 on double-decide, PO approval, audit records written.

Run with `pytest -q`. Lint with `ruff check src tests`. CI runs both plus a Docker build on every push.

## Backtesting the forecast (how to do it yourself)

The repo does not ship a backtest harness yet, but the forecaster is a pure function, so one is short to write: for each SKU, walk the demand history, forecast from each cutoff, and compare against actuals over the horizon. Suggested metrics: MAE and bias (mean error) per SKU, plus service-level attainment (fraction of days with stock available) when the plan is simulated against the history. If you build this, put it in `tests/` so it runs in CI.

## What is deliberately not evaluated by tests

The optional LLM summary rewrite. It is presentation only; correctness of the plan does not depend on it. If you enable a model, review a few summaries by hand before showing them to planners.
