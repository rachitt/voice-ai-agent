from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PhoneNumberCreate(BaseModel):
    e164: str = Field(..., pattern=r"^\+[1-9]\d{6,14}$")
    provider: str = "telnyx"
    provider_resource_id: str | None = None
    agent_id: str | None = None


class PhoneNumberUpdate(BaseModel):
    agent_id: str | None = None
    status: str | None = None


class PhoneNumberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    e164: str
    provider: str
    provider_resource_id: str | None
    agent_id: str | None
    status: str
    created_at: datetime
