"""add batch_id, user_id, legal_hold, and retention indices to ecm_documents

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-11-19 13:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a1b2'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ecm_documents') as batch_op:
        batch_op.add_column(sa.Column('batch_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('user_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('legal_hold', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('retention_expires_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_ecm_documents_batch_id'), ['batch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ecm_documents_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ecm_documents_retention_expires_at'), ['retention_expires_at'], unique=False)
        batch_op.create_index('idx_doc_model_conf', ['classifier_version', 'confidence'], unique=False)
        batch_op.create_index('idx_doc_batch_status', ['batch_id', 'review_status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('ecm_documents') as batch_op:
        batch_op.drop_index('idx_doc_batch_status')
        batch_op.drop_index('idx_doc_model_conf')
        batch_op.drop_index(batch_op.f('ix_ecm_documents_retention_expires_at'))
        batch_op.drop_index(batch_op.f('ix_ecm_documents_user_id'))
        batch_op.drop_index(batch_op.f('ix_ecm_documents_batch_id'))
        batch_op.drop_column('retention_expires_at')
        batch_op.drop_column('legal_hold')
        batch_op.drop_column('user_id')
        batch_op.drop_column('batch_id')
