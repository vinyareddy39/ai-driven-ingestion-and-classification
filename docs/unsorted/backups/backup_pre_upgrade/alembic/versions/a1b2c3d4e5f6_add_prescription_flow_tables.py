"""add prescription flow tables

Revision ID: a1b2c3d4e5f6
Revises: 07595e940744
Create Date: 2026-11-19 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '07595e940744'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=32), server_default='patient', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('disabled', sa.Boolean(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # 2. prescriptions table
    op.create_table(
        'prescriptions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('file_key', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='QUEUED', nullable=False),
        sa.Column('model_version', sa.String(length=50), server_default='v1.0', nullable=True),
        sa.Column('ocr_engine', sa.String(length=50), server_default='HybridPyMuPDF-Tesseract', nullable=True),
        sa.Column('pii_detected', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prescriptions_file_key'), 'prescriptions', ['file_key'], unique=False)
    op.create_index(op.f('ix_prescriptions_status'), 'prescriptions', ['status'], unique=False)
    op.create_index(op.f('ix_prescriptions_user_id'), 'prescriptions', ['user_id'], unique=False)

    # 3. extracted_items table
    op.create_table(
        'extracted_items',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('prescription_id', sa.String(length=36), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('drug_name', sa.String(length=255), nullable=False),
        sa.Column('strength', sa.String(length=100), nullable=True),
        sa.Column('dose', sa.String(length=100), nullable=True),
        sa.Column('frequency', sa.String(length=100), nullable=True),
        sa.Column('timing', sa.String(length=100), nullable=True),
        sa.Column('duration_days', sa.Integer(), nullable=True),
        sa.Column('schedule_rule', sa.String(length=255), nullable=True),
        sa.Column('confidence_json', sa.Text(), nullable=True),
        sa.Column('verified_by_user', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['prescription_id'], ['prescriptions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_extracted_items_prescription_id'), 'extracted_items', ['prescription_id'], unique=False)
    op.create_index(op.f('ix_extracted_items_verified_by_user'), 'extracted_items', ['verified_by_user'], unique=False)

    # 4. timetable_slots table
    op.create_table(
        'timetable_slots',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('prescription_id', sa.String(length=36), nullable=False),
        sa.Column('extracted_item_id', sa.String(length=36), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('instruction', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
        sa.Column('status_changed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['extracted_item_id'], ['extracted_items.id'], ),
        sa.ForeignKeyConstraint(['prescription_id'], ['prescriptions.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_timetable_slots_extracted_item_id'), 'timetable_slots', ['extracted_item_id'], unique=False)
    op.create_index(op.f('ix_timetable_slots_prescription_id'), 'timetable_slots', ['prescription_id'], unique=False)
    op.create_index(op.f('ix_timetable_slots_scheduled_at'), 'timetable_slots', ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_timetable_slots_status'), 'timetable_slots', ['status'], unique=False)
    op.create_index(op.f('ix_timetable_slots_user_id'), 'timetable_slots', ['user_id'], unique=False)

    # 5. reminders table
    op.create_table(
        'reminders',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('slot_id', sa.String(length=36), nullable=False),
        sa.Column('channel', sa.String(length=32), server_default='email', nullable=False),
        sa.Column('send_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['slot_id'], ['timetable_slots.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reminders_send_at'), 'reminders', ['send_at'], unique=False)
    op.create_index(op.f('ix_reminders_slot_id'), 'reminders', ['slot_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reminders_slot_id'), table_name='reminders')
    op.drop_index(op.f('ix_reminders_send_at'), table_name='reminders')
    op.drop_table('reminders')

    op.drop_index(op.f('ix_timetable_slots_user_id'), table_name='timetable_slots')
    op.drop_index(op.f('ix_timetable_slots_status'), table_name='timetable_slots')
    op.drop_index(op.f('ix_timetable_slots_scheduled_at'), table_name='timetable_slots')
    op.drop_index(op.f('ix_timetable_slots_prescription_id'), table_name='timetable_slots')
    op.drop_index(op.f('ix_timetable_slots_extracted_item_id'), table_name='timetable_slots')
    op.drop_table('timetable_slots')

    op.drop_index(op.f('ix_extracted_items_verified_by_user'), table_name='extracted_items')
    op.drop_index(op.f('ix_extracted_items_prescription_id'), table_name='extracted_items')
    op.drop_table('extracted_items')

    op.drop_index(op.f('ix_prescriptions_user_id'), table_name='prescriptions')
    op.drop_index(op.f('ix_prescriptions_status'), table_name='prescriptions')
    op.drop_index(op.f('ix_prescriptions_file_key'), table_name='prescriptions')
    op.drop_table('prescriptions')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
