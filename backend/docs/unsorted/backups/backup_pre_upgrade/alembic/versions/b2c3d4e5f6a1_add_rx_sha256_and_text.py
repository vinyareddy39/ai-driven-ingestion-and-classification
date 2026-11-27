"""add sha256, raw_text, error_message to prescriptions

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-11-19 12:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('prescriptions', sa.Column('sha256', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_prescriptions_sha256'), 'prescriptions', ['sha256'], unique=False)
    op.add_column('prescriptions', sa.Column('raw_text', sa.Text(), nullable=True))
    op.add_column('prescriptions', sa.Column('error_message', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('prescriptions') as batch_op:
        batch_op.drop_index(op.f('ix_prescriptions_sha256'))
        batch_op.drop_column('error_message')
        batch_op.drop_column('raw_text')
        batch_op.drop_column('sha256')
