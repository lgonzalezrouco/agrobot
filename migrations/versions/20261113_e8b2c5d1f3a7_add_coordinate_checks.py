"""add coordinate checks

Revision ID: e8b2c5d1f3a7
Revises: d4f9a1c2e7b3
Create Date: 2026-11-13 12:00:00.000000+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8b2c5d1f3a7"
down_revision: str | Sequence[str] | None = "d4f9a1c2e7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("fields", "locations")


def upgrade() -> None:
    for table in TABLES:
        op.create_check_constraint("latitude_range", table, "latitude BETWEEN -90 AND 90")
        op.create_check_constraint("longitude_range", table, "longitude BETWEEN -180 AND 180")


def downgrade() -> None:
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_longitude_range"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_latitude_range"), table, type_="check")
