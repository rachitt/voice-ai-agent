from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SquadEdgeIn(BaseModel):
    from_agent_id: str
    to_agent_id: str
    context_policy: str = Field("last", pattern=r"^(none|last|all)$")
    context_n: int = 10
    condition: str | None = None


class SquadCreate(BaseModel):
    name: str
    root_agent_id: str
    edges: list[SquadEdgeIn] = []


class SquadEdgeOut(SquadEdgeIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class SquadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    root_agent_id: str
    created_at: datetime
    edges: list[SquadEdgeOut] = []
