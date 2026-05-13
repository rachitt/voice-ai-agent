from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KbCreate(BaseModel):
    name: str
    embedding_model: str = "text-embedding-3-small"


class KbOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    embedding_model: str
    created_at: datetime


class KbSourceCreate(BaseModel):
    name: str
    kind: str  # "pdf" | "txt" | "md" | "docx" | "url"
    s3_key: str | None = None


class KbSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kb_id: str
    name: str
    kind: str
    status: str
    error: str | None
    created_at: datetime


class KbQuery(BaseModel):
    query: str
    top_k: int = 5


class KbQueryHit(BaseModel):
    chunk_id: str
    source_id: str
    source_name: str | None = None
    text: str
    score: float


class KbQueryResult(BaseModel):
    hits: list[KbQueryHit]
    elapsed_ms: int = 0
