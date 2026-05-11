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


class ToolOut(ToolIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
