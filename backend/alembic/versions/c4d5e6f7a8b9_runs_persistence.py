"""runs and run_steps tables

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-11 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('graph_version_id', sa.Uuid(), nullable=True),
        sa.Column('trigger_source', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('input_json', sa.JSON(), nullable=False),
        sa.Column('output_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['graph_id'], ['graphs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['graph_version_id'], ['graph_versions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_runs_graph_id_started_at', 'runs', ['graph_id', sa.text('started_at DESC')])
    op.create_index('ix_runs_status', 'runs', ['status'])

    op.create_table(
        'run_steps',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('node_key', sa.String(length=128), nullable=False),
        sa.Column('node_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('input_snapshot', sa.JSON(), nullable=True),
        sa.Column('output_snapshot', sa.JSON(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_run_steps_run_id_step_order', 'run_steps', ['run_id', 'step_order'])


def downgrade() -> None:
    op.drop_index('ix_run_steps_run_id_step_order', table_name='run_steps')
    op.drop_table('run_steps')
    op.drop_index('ix_runs_status', table_name='runs')
    op.drop_index('ix_runs_graph_id_started_at', table_name='runs')
    op.drop_table('runs')
