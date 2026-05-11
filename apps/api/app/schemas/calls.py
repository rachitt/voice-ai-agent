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


class WebCallCreated(CallOut):
    """Web-call create response includes a short-lived WS session token."""
    ws_token: str
    ws_url: str


class StreamTokenOut(BaseModel):
    token: str
    expires_at: int
    ttl_seconds: int


class CallListItem(BaseModel):
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
    has_recording: bool = False
    created_at: datetime


class CallListPage(BaseModel):
    items: list[CallListItem]
    next_cursor: str | None = None
    total: int | None = None


class CallDetailOut(CallOut):
    """Full detail including transcript + provider IDs for the review page."""
    transcript: list[dict] | None = None
    provider_call_id: str | None = None
    phone_number_id: str | None = None
