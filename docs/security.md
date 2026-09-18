# Security

## Threat model

Meridian plans replenishment and drafts purchase orders. The assets that matter are the approval flow (money moves on approval), the audit trail (proof of who decided what), and the catalog data (demand history, supplier costs).

## Controls in place

- **Human-in-the-loop for spend.** Orders at or above `MERIDIAN_APPROVAL_THRESHOLD` cannot be released without an explicit approve call that records the approver. Below-threshold orders are released by policy as `policy:auto` with status `auto_approved` and a `decision.auto_approved` audit event, so they are distinguishable from human approvals. A PO itself can only be approved once every linked decision is `approved` or `auto_approved`; rejecting a decision holds its draft POs (`on_hold`).
- **Policy guardrails.** Unapproved suppliers are blocked, not skipped; over-cap orders are blocked for human review, not silently trimmed or split into over-cap POs. Blocks are persisted as decisions with reasons and audit events, and are visible in the run summary.
- **Audit trail.** Every run, decision state change, and PO approval writes an append-style audit event with actor, timestamp, and details.
- **Secrets handling.** Database credentials and the LLM key arrive via environment variables or a Kubernetes Secret. They are never logged and never appear in API responses. The Docker image ships no credentialed database default; `docker-compose.yml` reads the Postgres password from `MERIDIAN_DB_PASSWORD` and fails fast when it is missing.
- **Compromised credential note.** The password `meridian` was previously committed in `Dockerfile`/`docker-compose.yml` history. Treat it as compromised: rotate it everywhere it was ever used (local Postgres, shared dev databases, any environment that reused it) and never reuse it.
- **Non-root containers.** The Docker image and the k8s manifest run as an unprivileged user.
- **Input validation.** Request bodies are validated with Pydantic; quantities and horizons are range-checked.

## Out of scope for this release

- Authentication and authorization. The API currently trusts its callers; in front of real users, terminate at an identity-aware proxy or add OIDC and map approval rights to roles.
- Rate limiting and WAF rules belong at the ingress.
- The LLM integration sends only the run summary numbers to the configured endpoint. If your summaries contain sensitive data, self-host the model or keep the provider at `none`.

## Reporting issues

Open a GitHub issue with "security:" in the title for anything that looks like a vulnerability in the approval or audit path.
