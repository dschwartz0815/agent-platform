"""multi-tenancy: AD group mappings, workspace fields, catalog visibility

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Workspaces (orgs) get a description
    with op.batch_alter_table('orgs') as batch:
        batch.add_column(sa.Column('description', sa.Text(), nullable=True))

    # Users: cached AD groups + last_seen; org_id becomes a nullable legacy column
    # (membership is derived from AD groups, not stored per-user)
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('ad_groups', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
        batch.alter_column('org_id', existing_type=sa.Uuid(), nullable=True)

    # AD group → (workspace, role) mappings
    op.create_table(
        'tenant_group_mappings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('ad_group', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'ad_group', name='uq_group_mapping_org_group'),
    )
    op.create_index(
        'ix_tenant_group_mappings_ad_group', 'tenant_group_mappings', ['ad_group']
    )

    # Catalog fields on both registries
    for table in ('agents', 'mcp_servers'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(
                'visibility', sa.String(length=16), nullable=False, server_default='private'
            ))
            batch.add_column(sa.Column('tags', sa.JSON(), nullable=True))
            batch.add_column(sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
            batch.add_column(sa.Column('source_id', sa.Uuid(), nullable=True))


def downgrade() -> None:
    for table in ('agents', 'mcp_servers'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('source_id')
            batch.drop_column('published_at')
            batch.drop_column('tags')
            batch.drop_column('visibility')

    op.drop_index('ix_tenant_group_mappings_ad_group', table_name='tenant_group_mappings')
    op.drop_table('tenant_group_mappings')

    with op.batch_alter_table('users') as batch:
        batch.alter_column('org_id', existing_type=sa.Uuid(), nullable=False)
        batch.drop_column('last_seen_at')
        batch.drop_column('ad_groups')

    with op.batch_alter_table('orgs') as batch:
        batch.drop_column('description')
