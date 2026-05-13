from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentVersionIn(BaseModel):
    first_message: str | None = None
    system_prompt: str | None = None
    model_id: str = "gemini/gemini-3.1-flash-lite"
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    stt_id: str = "deepgram-nova-3"
    language: str = "en"
    interruption_sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    vad_silence_ms: int = Field(700, ge=100, le=3000)
    flow_graph: dict[str, Any] | None = None
    tools: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    analysis_plan: dict[str, Any] | None = None
    dynamic_variables: dict[str, Any] = Field(default_factory=dict)
    server_url: str | None = None


class AgentCreate(AgentVersionIn):
    name: str


class AgentUpdate(AgentVersionIn):
    name: str | None = None


class AgentVersionOut(AgentVersionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    version: int
    env: str
    created_at: datetime


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    published_version_id: str | None
    created_at: datetime
    updated_at: datetime


class AgentDetail(AgentOut):
    versions: list[AgentVersionOut]


class PublishIn(BaseModel):
    version_id: str
    env: str = "production"
