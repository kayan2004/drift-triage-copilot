"""initial_schema

Revision ID: 1e7c3e5bd8b8
Revises:
Create Date: 2026-05-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1e7c3e5bd8b8"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("input_features", sa.JSON(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("label", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "drift_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("ok", "warn", "critical", name="severity_enum"),
            nullable=False,
        ),
        sa.Column("psi_scores", sa.JSON(), nullable=True),
        sa.Column("chi2_scores", sa.JSON(), nullable=True),
        sa.Column("output_drift", sa.Float(), nullable=True),
        sa.Column("raw_report", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("drift_reports")
    op.drop_table("predictions")
    op.execute("DROP TYPE IF EXISTS severity_enum")
