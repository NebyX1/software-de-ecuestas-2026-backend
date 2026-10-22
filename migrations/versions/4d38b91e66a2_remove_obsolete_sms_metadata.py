"""Remove SMS-provider metadata without changing opinions or duplicate claims.

Revision ID: 4d38b91e66a2
Revises: 022a20c61d0e
"""
from alembic import op
import sqlalchemy as sa

revision = '4d38b91e66a2'
down_revision = '022a20c61d0e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('survey_invitations') as table:
        table.drop_column('phone_hash')
        table.drop_column('phone_verification_sid')
        table.drop_column('phone_started_at')
        table.drop_column('phone_verified_at')
        table.drop_column('phone_attempts')
        table.drop_column('phone_send_count')


def downgrade():
    # Old SMS verification state cannot be reconstructed; restore empty columns.
    # Counts receive a server default so existing invitations remain valid rows.
    with op.batch_alter_table('survey_invitations') as table:
        table.add_column(sa.Column('phone_hash', sa.String(64), nullable=True))
        table.add_column(sa.Column('phone_verification_sid', sa.String(34), nullable=True))
        table.add_column(sa.Column('phone_started_at', sa.DateTime(), nullable=True))
        table.add_column(sa.Column('phone_verified_at', sa.DateTime(), nullable=True))
        table.add_column(sa.Column('phone_attempts', sa.Integer(), nullable=False, server_default='0'))
        table.add_column(sa.Column('phone_send_count', sa.Integer(), nullable=False, server_default='0'))
