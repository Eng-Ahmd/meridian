"""Audit trail helpers. Every state-changing action records who did what, when,
and on the basis of which inputs, so a plan can always be reconstructed."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def inputs_hash(inputs: dict[str, Any]) -> str:
    canonical = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def audit_record(
    *,
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "actor": actor,
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "details": details or {},
    }
