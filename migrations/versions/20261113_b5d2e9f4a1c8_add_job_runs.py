"""add job runs

Revision ID: b5d2e9f4a1c8
Revises: e8b2c5d1f3a7
Create Date: 2026-11-13 18:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5d2e9f4a1c8"
down_revision: str | Sequence[str] | None = "e8b2c5d1f3a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("job", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum("succeeded", "failed", "timed_out", name="job_outcome"),
            nullable=False,
        ),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("counters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job"),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
    sa.Enum(name="job_outcome").drop(op.get_bind())
