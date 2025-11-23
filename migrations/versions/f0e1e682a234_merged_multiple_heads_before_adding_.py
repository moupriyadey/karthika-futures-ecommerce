"""Merged multiple heads before adding discount_price

Revision ID: f0e1e682a234
Revises: 184ff1fbd21a, 903609f7316c
Create Date: 2025-10-11 20:49:08.935178

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f0e1e682a234'
down_revision = ('184ff1fbd21a', '903609f7316c')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
