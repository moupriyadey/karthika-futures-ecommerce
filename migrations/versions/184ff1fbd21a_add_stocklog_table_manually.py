"""Add StockLog table manually"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # Import for using server_default

# You MUST ensure your revision and down_revision match the IDs in your file
revision = '184ff1fbd21a'  # <-- CONFIRM THIS MATCHES YOUR FILENAME ID
down_revision = None   # <-- Use the actual previous ID from the file
branch_labels = None
depends_on = None


def upgrade():
    # COMMANDS TO CREATE THE stock_log TABLE
    op.create_table('stock_log',
        # ID is the primary key (UUID in Python maps to String(36) in SQL)
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        
        # Foreign Key to the artwork table
        sa.Column('artwork_id', sa.String(length=36), sa.ForeignKey('artwork.id'), nullable=False),
        
        # Core data
        sa.Column('change_quantity', sa.Integer(), nullable=False),
        sa.Column('current_stock', sa.Integer(), nullable=False),
        sa.Column('change_type', sa.String(length=50), nullable=False),
        
        # Optional Foreign Keys: order.id is String(10)
        sa.Column('order_id', sa.String(length=10), sa.ForeignKey('order.id'), nullable=True),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        
        # Metadata
        sa.Column('remarks', sa.Text(), nullable=True),
        # Use server_default to set the timestamp when row is created
        sa.Column('timestamp', sa.DateTime(), server_default=sa.func.now(), nullable=False), 
        
        # Explicit Index for performance on the Foreign Key
        sa.Index('idx_stock_log_artwork_id', 'artwork_id')
    )
    # Primary key constraint is implicitly handled by primary_key=True on the 'id' column.


def downgrade():
    # COMMANDS TO DROP THE stock_log TABLE for rollback safety
    op.drop_table('stock_log')