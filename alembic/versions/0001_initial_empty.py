"""Initial empty migration.

Revision ID: 0001_initial_empty
Revises:
Create Date: 2026-08-27
"""

from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "0001_initial_empty"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create no tables until the data layer is introduced."""


def downgrade() -> None:
    """Revert no tables until the data layer is introduced."""
