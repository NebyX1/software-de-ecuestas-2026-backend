"""Record descriptive device metadata for responses; legacy rows remain NULL.

Revision ID: 9a7e3c2d1f60
Revises: 4d38b91e66a2
"""
from alembic import op
import sqlalchemy as sa

revision = '9a7e3c2d1f60'
down_revision = '4d38b91e66a2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('survey_responses') as table:
        table.add_column(sa.Column('device_metadata', sa.JSON(), nullable=True))
        table.add_column(sa.Column('device_type', sa.String(16), nullable=True))
        table.add_column(sa.Column('os_family', sa.String(24), nullable=True))
        table.add_column(sa.Column('browser_family', sa.String(24), nullable=True))
        table.add_column(sa.Column('browser_context', sa.String(24), nullable=True))
        for name in ('device_type', 'os_family', 'browser_family', 'browser_context'):
            table.create_index('ix_response_' + name, ['survey_id', name])


def downgrade():
    with op.batch_alter_table('survey_responses') as table:
        for name in ('device_type', 'os_family', 'browser_family', 'browser_context'):
            table.drop_index('ix_response_' + name)
        for name in ('device_metadata', 'device_type', 'os_family', 'browser_family', 'browser_context'):
            table.drop_column(name)
