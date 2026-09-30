"""add FAQ test marker

Revision ID: 9d5c2a71b3e4
Revises: fe2b1c0b91da
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d5c2a71b3e4"
down_revision: str | Sequence[str] | None = "fe2b1c0b91da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "faq",
        sa.Column(
            "is_test",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("faq", "is_test")
