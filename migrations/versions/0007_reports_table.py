"""reports table

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26 04:40:00.000000

PDFs are generated to disk (reports/{request_id}.pdf) and referenced by
path here, rather than stored as a DB blob — keeps either backend lean.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("generated_at", sa.String(40), nullable=False),
    )
    op.create_index("idx_reports_request_id", "reports", ["request_id"])


def downgrade() -> None:
    op.drop_index("idx_reports_request_id", table_name="reports")
    op.drop_table("reports")
