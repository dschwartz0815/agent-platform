"""add graph_versions table, schemas, slugs

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # orgs.slug — nullable first, backfill, then enforce unique
    op.add_column('orgs', sa.Column('slug', sa.String(length=128), nullable=True))
    op.execute(
        "UPDATE orgs SET slug = 'demo' WHERE slug IS NULL"
    )
    with op.batch_alter_table('orgs') as batch_op:
        batch_op.alter_column('slug', existing_type=sa.String(length=128), nullable=False)
        batch_op.create_unique_constraint('uq_orgs_slug', ['slug'])

    # graphs new columns
    op.add_column('graphs', sa.Column('slug', sa.String(length=128), nullable=True))
    op.add_column('graphs', sa.Column('input_schema', sa.JSON(), nullable=True))
    op.add_column('graphs', sa.Column('output_schema', sa.JSON(), nullable=True))
    op.add_column('graphs', sa.Column('latest_published_version_id', sa.Uuid(), nullable=True))
    op.add_column('graphs', sa.Column('retention_days', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('graphs', sa.Column('test_examples', sa.JSON(), nullable=True))

    # Backfill the seeded graph with its canonical slug
    op.execute(
        "UPDATE graphs SET slug = 'change-risk-analyzer' "
        "WHERE id = '00000000-0000-0000-0000-000000000020' AND slug IS NULL"
    )

    with op.batch_alter_table('graphs') as batch_op:
        batch_op.create_unique_constraint(
            'uq_graphs_org_slug', ['org_id', 'slug']
        )

    # graph_versions table
    op.create_table(
        'graph_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('definition_json', sa.JSON(), nullable=False),
        sa.Column('input_schema', sa.JSON(), nullable=True),
        sa.Column('output_schema', sa.JSON(), nullable=True),
        sa.Column('published_by', sa.Uuid(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['graph_id'], ['graphs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['published_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('graph_id', 'version', name='uq_graph_versions_graph_id_version'),
    )
    op.create_index(
        'ix_graph_versions_graph_id',
        'graph_versions',
        ['graph_id'],
    )

    # latest_published_version_id FK — defined separately so graph_versions exists first
    with op.batch_alter_table('graphs') as batch_op:
        batch_op.create_foreign_key(
            'fk_graphs_latest_published_version_id',
            'graph_versions',
            ['latest_published_version_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('graphs') as batch_op:
        batch_op.drop_constraint('fk_graphs_latest_published_version_id', type_='foreignkey')

    op.drop_index('ix_graph_versions_graph_id', table_name='graph_versions')
    op.drop_table('graph_versions')

    with op.batch_alter_table('graphs') as batch_op:
        batch_op.drop_constraint('uq_graphs_org_slug', type_='unique')

    op.drop_column('graphs', 'test_examples')
    op.drop_column('graphs', 'retention_days')
    op.drop_column('graphs', 'latest_published_version_id')
    op.drop_column('graphs', 'output_schema')
    op.drop_column('graphs', 'input_schema')
    op.drop_column('graphs', 'slug')

    with op.batch_alter_table('orgs') as batch_op:
        batch_op.drop_constraint('uq_orgs_slug', type_='unique')

    op.drop_column('orgs', 'slug')
