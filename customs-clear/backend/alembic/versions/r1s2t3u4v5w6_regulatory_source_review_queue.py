"""Add durable queue for scheduled regulatory-source reviews.

Revision ID: r1s2t3u4v5w6
Revises: h3i4j5k6l7m8
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r1s2t3u4v5w6"
down_revision: Union[str, Sequence[str], None] = "h3i4j5k6l7m8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "regulatory_source_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("due_period", sa.String(length=7), nullable=False),
        sa.Column(
            "strategy",
            sa.String(length=32),
            server_default="local_reconcile",
            nullable=False,
        ),
        sa.Column("cadence", sa.String(length=16), server_default="monthly", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("evidence_scope", sa.String(length=64), nullable=False),
        sa.Column("evidence_manifest", sa.JSON(), nullable=False),
        sa.Column("first_raised_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_raised_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), server_default="", nullable=False),
        sa.Column("asserted_by", sa.String(length=128), server_default="", nullable=False),
        sa.Column("resolution_ref", sa.String(length=2048), server_default="", nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column(
            "superseded_by_evidence_sha256",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
        sa.Column("superseded_by_generation", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'superseded')",
            name="ck_regulatory_source_reviews_status",
        ),
        sa.CheckConstraint(
            "occurrence_count >= 1",
            name="ck_regulatory_source_reviews_occurrence_count",
        ),
        sa.CheckConstraint(
            "length(evidence_sha256) = 64",
            name="ck_regulatory_source_reviews_evidence_sha256",
        ),
        sa.CheckConstraint(
            "evidence_generation >= 1",
            name="ck_regulatory_source_reviews_evidence_generation",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL "
            "AND resolved_by = '' AND asserted_by = '' AND resolution_ref = '' "
            "AND superseded_at IS NULL AND superseded_by_evidence_sha256 = '' "
            "AND superseded_by_generation IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL "
            "AND length(trim(resolved_by)) > 0 "
            "AND length(trim(asserted_by)) > 0 "
            "AND length(trim(resolution_ref)) > 0 "
            "AND ((superseded_at IS NULL AND superseded_by_evidence_sha256 = '' "
            "AND superseded_by_generation IS NULL) "
            "OR (superseded_at IS NOT NULL "
            "AND length(superseded_by_evidence_sha256) = 64 "
            "AND superseded_by_evidence_sha256 <> evidence_sha256 "
            "AND superseded_by_generation IS NOT NULL "
            "AND superseded_by_generation > evidence_generation))) "
            "OR (status = 'superseded' AND resolved_at IS NULL "
            "AND resolved_by = '' AND asserted_by = '' AND resolution_ref = '' "
            "AND superseded_at IS NOT NULL "
            "AND length(superseded_by_evidence_sha256) = 64 "
            "AND superseded_by_evidence_sha256 <> evidence_sha256 "
            "AND superseded_by_generation IS NOT NULL "
            "AND superseded_by_generation > evidence_generation)",
            name="ck_regulatory_source_reviews_resolution_state",
        ),
    )
    op.create_index(
        op.f("ix_regulatory_source_reviews_source_id"),
        "regulatory_source_reviews",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_regulatory_source_reviews_due_period"),
        "regulatory_source_reviews",
        ["due_period"],
        unique=False,
    )
    op.create_index(
        op.f("ix_regulatory_source_reviews_status"),
        "regulatory_source_reviews",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_regulatory_source_reviews_one_pending_source",
        "regulatory_source_reviews",
        ["source_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("regulatory_source_reviews")
