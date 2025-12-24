"""Add display_order to Category (SAFE CLEAN MIGRATION)

Revision ID: a84eeb9558fb
Revises: a7bc208679d4
Create Date: 2025-12-24

This migration was cleaned manually to avoid
accidental data loss from auto-generated commands.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a84eeb9558fb'
down_revision = 'a7bc208679d4'
branch_labels = None
depends_on = None


def upgrade():
    """
    SAFE UPGRADE:
    - Do nothing
    - Column already added manually via SQL (Neon DB)
    """
    pass


def downgrade():
    """
    SAFE DOWNGRADE:
    - Do nothing
    """
    pass
