# Architecture

## Components

```
                    +------------------+
                    |   Dashboard      |  web/ (static, served by the API)
                    +--------+---------+
                             | HTTP
                    +--------v---------+
                    |   FastAPI        |  src/meridian/api/
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v------+ +----v-----+ +------v------+
     | Orchestrator  | | Policy   | | Audit       |
     +--------+------+ +----------+ +-------------+
              | runs, in order
   +----------+-----------+------------------+------------------+
   |          |           |                  |                  |
+--v---+ +----v-----+ +---v------+ +---------v--------+ +-------v-------+
|Fore- | |Inventory | | Risk     | | Procurement      | | LLM (optional)|
|cast  | |          | |          | |                  | | summaries     |
+------+ +----------+ +----------+ +------------------+ +---------------+
```

The orchestrator (`agents/orchestrator.py`) executes the four agents in a fixed sequence for each run. Agents read from a shared `PlanningContext` and return findings; they never write to the database directly. The orchestrator persists runs, decisions, purchase orders, and audit events through the repository layer (`store/repository.py`).

## Data flow

1. `POST /v1/runs` creates a `runs` row with status `running`, then loads the catalog from CSV (`data/loader.py`). A load failure flips the run to `failed` with an audit event and returns 422 naming the file and row — every run attempt is recorded.
2. The run's inputs hash is SHA-256 over the raw bytes of the five catalog CSVs (sorted by filename) so a run can be tied back to its exact inputs: any byte-level change in costs, inventory, suppliers, or demand produces a different hash.
3. Forecaster, Inventory, Risk, and Procurement run in order. Procurement receives the inventory findings through the context.
4. Policy guardrails (`core/policy.py`) evaluate every proposed order: unapproved suppliers are blocked, orders whose value (or single-unit cost) exceeds the cap are blocked for human review, large cover quantities are flagged advisory-only ("quantity covers ~N days of forecast horizon; review advised" — quantities are never silently trimmed), and orders at or above the approval threshold are marked `needs_approval`.
5. Decisions and draft POs are written with status, rationale, and confidence: below-threshold orders persist as `auto_approved` (`decided_by="policy:auto"` plus a `decision.auto_approved` audit event), blocked proposals persist as `blocked` with the reason in `extra` plus a `decision.blocked` audit event. The run is marked `succeeded` with a summary; any exception marks it `failed` and is recorded.

## Why this shape

- **Deterministic core.** Planning math uses fixed statistical methods. Given the same catalog and params, a run reproduces exactly. This makes the system testable, auditable, and safe to demo.
- **LLM at the edge.** The optional model only rewrites the summary paragraph. A failed or missing LLM call falls back to a template; planning never depends on it. Rationale: `docs/adr/001-deterministic-core.md`.
- **Human-in-the-loop by default.** Money does not move without approval. The threshold is configuration, and every approval records who decided and when.
- **Boring persistence.** A relational store with explicit tables beats a vector DB for orders and audit. SQLite for local work, Postgres for production, same code path.

## Scaling notes

Request-scoped execution is fine for catalogs up to tens of thousands of SKUs. Past that, move run execution to a worker queue (Celery or arq) and have `POST /v1/runs` return a run id immediately; the status and summary endpoints already support polling. The agents themselves are pure functions over the context, so they parallelize per SKU with no changes.
