"""add notification lease

Revision ID: d4f9a1c2e7b3
Revises: c3e8f1a2b4d6
Create Date: 2026-11-13 10:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f9a1c2e7b3"
down_revision: str | Sequence[str] | None = "c3e8f1a2b4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications", sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notifications", "leased_until")
