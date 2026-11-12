"""add alerts

Revision ID: 536b69780b55
Revises: f102f29c08e0
Create Date: 2026-11-12 03:11:39.922007+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "536b69780b55"
down_revision: str | Sequence[str] | None = "f102f29c08e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column(
            "weather_event_type",
            sa.Enum("frost", "rain", "hail", "heat_wave", "strong_wind", name="weather_event_type"),
            nullable=False,
        ),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_id", "weather_event_type"),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    sa.Enum(name="weather_event_type").drop(op.get_bind())
