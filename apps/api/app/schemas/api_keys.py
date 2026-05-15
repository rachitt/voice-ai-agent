from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyOut):
    """One-shot response on mint — `key` is shown ONCE and never persisted in plaintext."""

    key: str
