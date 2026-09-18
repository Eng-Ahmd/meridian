"""Request and response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _strip_name(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


class RunRequest(BaseModel):
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    service_level: float | None = Field(default=None, ge=0.90, le=0.995)
    review_period_days: int | None = Field(default=None, ge=1, le=90)
    requested_by: str = Field(default="api", max_length=128)

    _strip_requested_by = field_validator("requested_by", mode="before")(
        classmethod(lambda cls, v: _strip_name(v, "requested_by"))
    )


class DecisionAction(BaseModel):
    decided_by: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)

    _strip_decided_by = field_validator("decided_by", mode="before")(
        classmethod(lambda cls, v: _strip_name(v, "decided_by"))
    )
    _strip_note = field_validator("note", mode="before")(
        classmethod(lambda cls, v: v.strip() if isinstance(v, str) else v)
    )


class ApprovalAction(BaseModel):
    approved_by: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)

    _strip_approved_by = field_validator("approved_by", mode="before")(
        classmethod(lambda cls, v: _strip_name(v, "approved_by"))
    )
    _strip_note = field_validator("note", mode="before")(
        classmethod(lambda cls, v: v.strip() if isinstance(v, str) else v)
    )
