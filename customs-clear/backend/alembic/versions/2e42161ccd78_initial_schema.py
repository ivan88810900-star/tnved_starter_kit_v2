"""initial_schema

Revision ID: 2e42161ccd78
Revises: 
Create Date: 2026-03-19 12:36:24.443041

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = '2e42161ccd78'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(name)


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    # Create hs_rates if not exists (for clean migration-from-scratch)
    if not _table_exists('hs_rates'):
        op.create_table(
            'hs_rates',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('hs_code', sa.String(length=10), nullable=False),
            sa.Column('hs_prefix', sa.String(length=10), nullable=False),
            sa.Column('duty_rate', sa.Float(), nullable=False, server_default='0'),
            sa.Column('vat_import_rate', sa.Float(), nullable=False, server_default='22'),
            sa.Column('vat_rule', sa.String(length=20), nullable=False, server_default='none'),
            sa.Column('vat_rule_basis', sa.Text(), nullable=False, server_default=''),
            sa.Column('excise_type', sa.String(length=20), nullable=False, server_default='none'),
            sa.Column('excise_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('excise_basis', sa.Text(), nullable=False, server_default=''),
            sa.Column('has_antidumping', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('antidumping_type', sa.String(length=20), nullable=False, server_default='none'),
            sa.Column('antidumping_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('antidumping_condition', sa.Text(), nullable=False, server_default=''),
            sa.Column('antidumping_countries', sa.Text(), nullable=False, server_default=''),
            sa.Column('valid_from', sa.String(length=20), nullable=False, server_default=''),
            sa.Column('valid_to', sa.String(length=20), nullable=False, server_default=''),
            sa.Column('source_url', sa.Text(), nullable=False, server_default=''),
            sa.Column('source_revision', sa.String(length=128), nullable=False, server_default='seed'),
            sa.PrimaryKeyConstraint('id'),
        )
        with op.batch_alter_table('hs_rates', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_hs_rates_hs_code'), ['hs_code'], unique=False)
            batch_op.create_index(batch_op.f('ix_hs_rates_hs_prefix'), ['hs_prefix'], unique=False)

    # Create source_status if not exists
    if not _table_exists('source_status'):
        op.create_table(
            'source_status',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('source_code', sa.String(length=50), nullable=False),
            sa.Column('source_name', sa.String(length=255), nullable=False),
            sa.Column('source_url', sa.Text(), nullable=False),
            sa.Column('revision', sa.String(length=128), nullable=False, server_default='unknown'),
            sa.Column('synced_at', sa.DateTime(), nullable=False),
            sa.Column('is_stale', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('note', sa.Text(), nullable=False, server_default=''),
            sa.PrimaryKeyConstraint('id'),
        )
        with op.batch_alter_table('source_status', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_source_status_source_code'), ['source_code'], unique=True)

    if not _table_exists('non_tariff_rules'):
        op.create_table(
            'non_tariff_rules',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('hs_prefix', sa.String(length=10), nullable=False),
            sa.Column('tr_ts', sa.Text(), nullable=False, server_default=''),
            sa.Column('required_permits', sa.Text(), nullable=False, server_default=''),
            sa.Column('valid_from', sa.String(length=20), nullable=False, server_default=''),
            sa.Column('valid_to', sa.String(length=20), nullable=False, server_default=''),
            sa.Column('source_url', sa.Text(), nullable=False, server_default=''),
            sa.Column('source_revision', sa.String(length=128), nullable=False, server_default='seed'),
            sa.PrimaryKeyConstraint('id'),
        )
        with op.batch_alter_table('non_tariff_rules', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_non_tariff_rules_hs_prefix'), ['hs_prefix'], unique=False)

    if not _table_exists('sync_log'):
        op.create_table(
            'sync_log',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('source_code', sa.String(length=50), nullable=False),
            sa.Column('synced_at', sa.DateTime(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='OK'),
            sa.Column('revision', sa.String(length=128), nullable=False, server_default=''),
            sa.Column('rows_affected', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('note', sa.Text(), nullable=False, server_default=''),
            sa.PrimaryKeyConstraint('id'),
        )
        with op.batch_alter_table('sync_log', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_sync_log_source_code'), ['source_code'], unique=False)

    # Add new columns to hs_rates only if they don't exist yet
    new_cols = [
        ('vat_rule', sa.String(length=20), 'none'),
        ('vat_rule_basis', sa.Text(), ''),
        ('excise_basis', sa.Text(), ''),
        ('antidumping_countries', sa.Text(), ''),
    ]
    with op.batch_alter_table('hs_rates', schema=None) as batch_op:
        for col_name, col_type, default in new_cols:
            if not _column_exists('hs_rates', col_name):
                batch_op.add_column(
                    sa.Column(col_name, col_type, nullable=False, server_default=default)
                )


def downgrade() -> None:
    with op.batch_alter_table('hs_rates', schema=None) as batch_op:
        for col_name in ('antidumping_countries', 'excise_basis', 'vat_rule_basis', 'vat_rule'):
            if _column_exists('hs_rates', col_name):
                batch_op.drop_column(col_name)

    if _table_exists('sync_log'):
        with op.batch_alter_table('sync_log', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_sync_log_source_code'))
        op.drop_table('sync_log')

    if _table_exists('non_tariff_rules'):
        with op.batch_alter_table('non_tariff_rules', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_non_tariff_rules_hs_prefix'))
        op.drop_table('non_tariff_rules')
