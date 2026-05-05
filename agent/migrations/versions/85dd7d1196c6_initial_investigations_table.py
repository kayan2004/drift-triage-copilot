"""initial investigations table

Revision ID: 85dd7d1196c6
Revises: 
Create Date: 2026-05-05 15:57:15.768514

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85dd7d1196c6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("investigation_id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("triage_summary", sa.Text(), nullable=True),
        sa.Column("proposed_action", sa.String(), nullable=True),
        sa.Column("hil_token", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("investigations")
