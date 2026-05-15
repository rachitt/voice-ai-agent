"""agent version dynamic_variables column

Revision ID: 4c1ae73c6f01
Revises: 3b254d828127
Create Date: 2026-05-11 22:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4c1ae73c6f01"
down_revision: str | None = "3b254d828127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column(
            "dynamic_variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_versions", "dynamic_variables")
