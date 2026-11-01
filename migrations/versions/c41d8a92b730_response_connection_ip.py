"""Record the actual submission IP; historical opinions remain unchanged.

Revision ID: c41d8a92b730
Revises: 9a7e3c2d1f60
"""
from alembic import op
import sqlalchemy as sa

revision = 'c41d8a92b730'
down_revision = '9a7e3c2d1f60'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('survey_responses') as table:
        table.add_column(sa.Column('ip_address', sa.String(45), nullable=True))


def downgrade():
    with op.batch_alter_table('survey_responses') as table:
        table.drop_column('ip_address')
