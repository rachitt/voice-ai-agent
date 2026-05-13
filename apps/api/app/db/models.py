from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import prefixed_id
from app.db.base import Base, TimestampMixin


class CallStatus(StrEnum):
    queued = "queued"
    ringing = "ringing"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class CallDirection(StrEnum):
    inbound = "inbound"
    outbound = "outbound"
    web = "web"


class AgentEnv(StrEnum):
    draft = "draft"
    staging = "staging"
    production = "production"


def _id(prefix: str) -> str:
    return prefixed_id(prefix)


class Org(Base, TimestampMixin):
    __tablename__ = "orgs"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("org"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("usr"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("key"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("ag"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    published_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_versions.id", use_alter=True, name="fk_agents_published_version")
    )

    versions: Mapped[list[AgentVersion]] = relationship(
        back_populates="agent", foreign_keys="AgentVersion.agent_id", cascade="all, delete-orphan"
    )


class AgentVersion(Base, TimestampMixin):
    __tablename__ = "agent_versions"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("agv"))
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    env: Mapped[str] = mapped_column(String(20), default=AgentEnv.draft, nullable=False)

    first_message: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(80), default="gemini/gemini-3.1-flash-lite", nullable=False)
    voice_id: Mapped[str] = mapped_column(String(80), default="21m00Tcm4TlvDq8ikWAM", nullable=False)
    stt_id: Mapped[str] = mapped_column(String(80), default="deepgram-nova-3", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)

    interruption_sensitivity: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    vad_silence_ms: Mapped[int] = mapped_column(Integer, default=700, nullable=False)

    flow_graph: Mapped[dict | None] = mapped_column(JSONB)
    tools: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    knowledge_base_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    analysis_plan: Mapped[dict | None] = mapped_column(JSONB)
    dynamic_variables: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    server_url: Mapped[str | None] = mapped_column(String(512))

    agent: Mapped[Agent] = relationship(back_populates="versions", foreign_keys=[agent_id])

    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_version"),)


class Tool(Base, TimestampMixin):
    __tablename__ = "tools"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("tool"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    server_url: Mapped[str] = mapped_column(String(512), nullable=False)
    method: Mapped[str] = mapped_column(String(8), default="POST", nullable=False)
    headers: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    params_schema: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_tools_org_name"),)


class PhoneNumber(Base, TimestampMixin):
    __tablename__ = "phone_numbers"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("pn"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    e164: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="telnyx", nullable=False)
    provider_resource_id: Mapped[str | None] = mapped_column(String(120))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("kb"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_model: Mapped[str] = mapped_column(
        String(80), default="text-embedding-3-small", nullable=False
    )


class KbSource(Base, TimestampMixin):
    __tablename__ = "kb_sources"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("kbs"))
    kb_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    s3_key: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class KbChunk(Base, TimestampMixin):
    __tablename__ = "kb_chunks"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("kbc"))
    kb_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    __table_args__ = (
        Index("ix_kb_chunks_embedding_ivfflat", "embedding", postgresql_using="ivfflat"),
    )


class Squad(Base, TimestampMixin):
    __tablename__ = "squads"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("sq"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    root_agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )

    edges: Mapped[list[SquadEdge]] = relationship(
        back_populates="squad", cascade="all, delete-orphan"
    )


class SquadEdge(Base, TimestampMixin):
    __tablename__ = "squad_edges"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("sqe"))
    squad_id: Mapped[str] = mapped_column(ForeignKey("squads.id", ondelete="CASCADE"), index=True)
    from_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    to_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    context_policy: Mapped[str] = mapped_column(String(16), default="last", nullable=False)
    context_n: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    condition: Mapped[str | None] = mapped_column(Text)

    squad: Mapped[Squad] = relationship(back_populates="edges")


class Call(Base, TimestampMixin):
    __tablename__ = "calls"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("call"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"))
    agent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL")
    )
    phone_number_id: Mapped[str | None] = mapped_column(
        ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=CallStatus.queued, nullable=False)

    from_number: Mapped[str | None] = mapped_column(String(32))
    to_number: Mapped[str | None] = mapped_column(String(32))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    recording_s3_key: Mapped[str | None] = mapped_column(String(512))
    transcript: Mapped[list | None] = mapped_column(JSONB)
    analysis: Mapped[dict | None] = mapped_column(JSONB)

    dynamic_variables: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(120), index=True)


class CallEvent(Base):
    __tablename__ = "call_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)


class WebhookOutbox(Base, TimestampMixin):
    __tablename__ = "webhook_outbox"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _id("whx"))
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
