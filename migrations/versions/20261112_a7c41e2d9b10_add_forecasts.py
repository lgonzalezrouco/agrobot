"""add forecasts

Revision ID: a7c41e2d9b10
Revises: 536b69780b55
Create Date: 2026-11-12 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c41e2d9b10"
down_revision: str | Sequence[str] | None = "536b69780b55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecasts",
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "weather_event_type",
            postgresql.ENUM(name="weather_event_type", create_type=False),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("probability", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "weather_event_type", "day"),
        sa.CheckConstraint("probability BETWEEN 0 AND 100", name="probability_range"),
    )


def downgrade() -> None:
    op.drop_table("forecasts")
