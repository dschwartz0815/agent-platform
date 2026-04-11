"""add a2a agent card and mcp tools cache

Revision ID: a2b3c4d5e6f7
Revises: f7d1bbf56602
Create Date: 2026-04-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f7d1bbf56602'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('agent_card_url', sa.Text(), nullable=True))
    op.add_column('agents', sa.Column('agent_card_json', sa.JSON(), nullable=True))
    op.add_column('mcp_servers', sa.Column('tools_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('mcp_servers', 'tools_json')
    op.drop_column('agents', 'agent_card_json')
    op.drop_column('agents', 'agent_card_url')
