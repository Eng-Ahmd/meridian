"""Request and response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    service_level: float | None = Field(default=None, ge=0.80, le=0.995)
    review_period_days: int | None = Field(default=None, ge=1, le=90)
    requested_by: str = Field(default="api", max_length=128)


class DecisionAction(BaseModel):
    decided_by: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)


class ApprovalAction(BaseModel):
    approved_by: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)
