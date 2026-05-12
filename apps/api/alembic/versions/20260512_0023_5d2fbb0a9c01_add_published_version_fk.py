"""add_published_version_fk

Revision ID: 5d2fbb0a9c01
Revises: 4c1ae73c6f01
Create Date: 2026-05-12 00:23:45.854044+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '5d2fbb0a9c01'
down_revision: str | None = '4c1ae73c6f01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Initial migration declared this FK with use_alter=True inside op.create_table;
    # SQLAlchemy drops use_alter FKs from CREATE TABLE DDL and metadata.create_all would
    # emit them as a follow-up ALTER, but op.create_table does not, so the constraint
    # was never created. Add it explicitly. IF NOT EXISTS keeps re-runs idempotent.
    op.execute(
        "ALTER TABLE agents "
        "ADD CONSTRAINT fk_agents_published_version "
        "FOREIGN KEY (published_version_id) REFERENCES agent_versions(id)"
    )


def downgrade() -> None:
    op.drop_constraint("fk_agents_published_version", "agents", type_="foreignkey")
