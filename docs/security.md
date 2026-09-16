# Security

## Threat model

Meridian plans replenishment and drafts purchase orders. The assets that matter are the approval flow (money moves on approval), the audit trail (proof of who decided what), and the catalog data (demand history, supplier costs).

## Controls in place

- **Human-in-the-loop for spend.** Orders at or above `MERIDIAN_APPROVAL_THRESHOLD` cannot be released without an explicit approve call that records the approver. There is no auto-approve path.
- **Policy guardrails.** Unapproved suppliers are blocked, not skipped; oversized orders are split, not silently trimmed. Blocks are visible in the run summary.
- **Audit trail.** Every run, decision state change, and PO approval writes an append-style audit event with actor, timestamp, and details.
- **Secrets handling.** Database credentials and the LLM key arrive via environment variables or a Kubernetes Secret. They are never logged and never appear in API responses.
- **Non-root containers.** The Docker image and the k8s manifest run as an unprivileged user.
- **Input validation.** Request bodies are validated with Pydantic; quantities and horizons are range-checked.

## Out of scope for this release

- Authentication and authorization. The API currently trusts its callers; in front of real users, terminate at an identity-aware proxy or add OIDC and map approval rights to roles.
- Rate limiting and WAF rules belong at the ingress.
- The LLM integration sends only the run summary numbers to the configured endpoint. If your summaries contain sensitive data, self-host the model or keep the provider at `none`.

## Reporting issues

Open a GitHub issue with "security:" in the title for anything that looks like a vulnerability in the approval or audit path.
