# Configuration

Every setting is an environment variable prefixed with `MERIDIAN_`. A `.env` file in the working directory is picked up automatically. Copy `.env.example` to `.env` to start.

## Reference

| Variable | Default | Notes |
|---|---|---|
| `MERIDIAN_ENVIRONMENT` | `development` | Free-form label, included in logs. |
| `MERIDIAN_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `MERIDIAN_DATABASE_URL` | `sqlite:///./data/meridian.db` | SQLAlchemy URL. Postgres example: `postgresql+psycopg2://user:pass@host:5432/meridian`. |
| `MERIDIAN_DATA_DIR` | `data` | Directory holding the catalog CSVs. |
| `MERIDIAN_LLM_PROVIDER` | `none` | Set to `openai-compatible` to enable narrative summaries. |
| `MERIDIAN_LLM_BASE_URL` | empty | e.g. `https://api.openai.com/v1`. |
| `MERIDIAN_LLM_API_KEY` | empty | Sent as a bearer token. |
| `MERIDIAN_LLM_MODEL` | empty | e.g. `gpt-4o-mini` or a self-hosted model name. |
| `MERIDIAN_MAX_SINGLE_PO_VALUE` | `25000` | A proposed order above this is blocked for human review (never auto-split into over-cap POs). |
| `MERIDIAN_APPROVAL_THRESHOLD` | `5000` | Orders at or above this value need human approval. |
| `MERIDIAN_DEFAULT_SERVICE_LEVEL` | `0.95` | Target fill rate used for safety stock. |
| `MERIDIAN_FORECAST_HORIZON_DAYS` | `30` | Default planning horizon. |
| `MERIDIAN_REVIEW_PERIOD_DAYS` | `7` | Days of demand covered beyond lead time. |

`MERIDIAN_LOG_LEVEL` accepts only `DEBUG`, `INFO`, `WARNING`, `ERROR`; anything else fails fast at startup.

Docker Compose additionally requires `MERIDIAN_DB_PASSWORD` in the environment (the Postgres password); compose fails fast with a clear message when it is missing. The password is never baked into the image.

## Tuning the policy guardrails

- Lower `MERIDIAN_APPROVAL_THRESHOLD` (e.g. to `1000`) when rolling out, so planners review nearly everything while trust is being built. Raise it once approval patterns are stable.
- `MERIDIAN_MAX_SINGLE_PO_VALUE` should match the largest PO your finance team will release without extra sign-off.
- Service level trades holding cost against stockout risk: 0.98 roughly doubles safety stock versus 0.90 for the same demand variability.

## LLM setup

The LLM only rewrites the run summary paragraph. To enable it with any OpenAI-compatible endpoint:

```bash
MERIDIAN_LLM_PROVIDER=openai-compatible
MERIDIAN_LLM_BASE_URL=https://your-endpoint/v1
MERIDIAN_LLM_API_KEY=...
MERIDIAN_LLM_MODEL=your-model
```

If the call fails or times out (20s), the run still succeeds and the summary uses the built-in template. Planning math never calls the model.
