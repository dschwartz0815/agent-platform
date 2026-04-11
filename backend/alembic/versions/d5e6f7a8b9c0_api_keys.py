"""api_keys table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-11 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('key_prefix', sa.String(length=24), nullable=False),
        sa.Column('key_hash', sa.Text(), nullable=False),
        sa.Column('key_last4', sa.String(length=4), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_keys_key_prefix', 'api_keys', ['key_prefix'])
    op.create_index('ix_api_keys_org_id', 'api_keys', ['org_id'])


def downgrade() -> None:
    op.drop_index('ix_api_keys_org_id', table_name='api_keys')
    op.drop_index('ix_api_keys_key_prefix', table_name='api_keys')
    op.drop_table('api_keys')
