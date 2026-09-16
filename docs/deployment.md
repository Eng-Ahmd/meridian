# Deployment

## Docker Compose (recommended for evaluation)

```bash
docker compose up --build
```

This starts Postgres 16 and the API (2-stage image, non-root user, health check). The API waits for the database to be healthy before starting. Data persists in the `pgdata` volume. The catalog CSVs are mounted read-only from `./data`.

## Kubernetes

`deploy/k8s/` contains a Deployment and a Service.

- 2 replicas, `runAsNonRoot`, liveness and readiness probes on `/health` and `/ready`, CPU/memory requests and limits.
- Database URL and the optional LLM key come from the `meridian-secrets` Secret; create it before applying:

```bash
kubectl create secret generic meridian-secrets \
  --from-literal=database-url='postgresql+psycopg2://...' \
  --from-literal=llm-api-key='...'
kubectl apply -f deploy/k8s/
```

Use a managed Postgres (RDS, Cloud SQL) rather than running the database in-cluster for anything beyond a demo.

## Production checklist

- Set `MERIDIAN_DATABASE_URL` to Postgres. SQLite is for local development only.
- Put the service behind TLS (ingress or load balancer); the app itself serves plain HTTP.
- Ship the log stream (stderr) to your collector; entries are JSON with `ts`, `level`, `logger`, and `run_id`/`agent` fields where relevant.
- Scrape `/metrics` with Prometheus; alert on `meridian_runs_total{status="failed"}` increasing and on `meridian_decisions_total{status="needs_approval"}` growing without bound (approvals piling up).
- Back up the database on your normal schedule. Runs, decisions, POs, and the audit trail all live there; the catalog CSVs live in version control or your data pipeline.
- Move run execution to a worker queue (Celery/arq) once runs take longer than a comfortable HTTP timeout. The API already exposes run status and summary for polling.

## Image

`docker build -t meridian:0.1.0 .` produces a slim runtime image with no dev dependencies. CI builds it on every push to `main`.
