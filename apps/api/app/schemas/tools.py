from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolIn(BaseModel):
    name: str
    description: str | None = None
    server_url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    params_schema: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = 10000


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    server_url: str | None = None
    method: str | None = None
    headers: dict[str, str] | None = None
    params_schema: dict[str, Any] | None = None
    timeout_ms: int | None = None


class ToolOut(ToolIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
