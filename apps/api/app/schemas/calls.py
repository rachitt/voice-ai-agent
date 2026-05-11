from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PhoneCallCreate(BaseModel):
    agent_id: str
    from_number: str = Field(..., pattern=r"^\+[1-9]\d{6,14}$")
    to_number: str = Field(..., pattern=r"^\+[1-9]\d{6,14}$")
    dynamic_variables: dict[str, Any] = Field(default_factory=dict)


class WebCallCreate(BaseModel):
    agent_id: str
    dynamic_variables: dict[str, Any] = Field(default_factory=dict)


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    agent_id: str
    direction: str
    status: str
    from_number: str | None
    to_number: str | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    recording_s3_key: str | None
    analysis: dict | None
    dynamic_variables: dict
    created_at: datetime
