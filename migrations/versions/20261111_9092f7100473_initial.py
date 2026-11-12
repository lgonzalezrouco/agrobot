"""initial

Revision ID: 9092f7100473
Revises:
Create Date: 2026-11-11 20:27:47.587949+00:00

"""

from collections.abc import Sequence

revision: str = "9092f7100473"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
