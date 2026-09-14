"""Versioned local ETT candidates; active rate tables remain untouched.

Revision ID: e1t2t3s4n5p6
Revises: r1s2t3u4v5w6
"""
from alembic import op
import sqlalchemy as sa

revision = "e1t2t3s4n5p6"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ett_snapshots",
        sa.Column("manifest_sha256", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(128), nullable=False, unique=True),
        sa.Column("coverage_from", sa.Date(), nullable=False),
        sa.Column("coverage_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("storage_kind", sa.String(32), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("staged_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(manifest_sha256) = 64", name="ck_ett_snapshot_digest"),
        sa.CheckConstraint("coverage_from < coverage_to", name="ck_ett_snapshot_dates"),
        sa.CheckConstraint("status = 'candidate'", name="ck_ett_snapshot_candidate_only"),
        sa.CheckConstraint("storage_kind = 'local_development'", name="ck_ett_snapshot_local_only"),
    )
    for table, key in (("ett_artifacts", "artifact_id"), ("ett_code_versions", "code"), ("ett_footnotes", "footnote_id")):
        constraints = [sa.CheckConstraint("length(code) = 10", name="ck_ett_code_length")] if key == "code" else []
        columns = [sa.Column("valid_from", sa.Date(), primary_key=True), sa.Column("valid_to", sa.Date(), nullable=False)] if key == "code" else []
        op.create_table(
            table,
            sa.Column("snapshot_sha256", sa.String(64), sa.ForeignKey("ett_snapshots.manifest_sha256"), primary_key=True),
            sa.Column(key, sa.String(10 if key == "code" else 128), primary_key=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            *columns,
            *constraints,
        )
    op.create_table(
        "ett_rate_rules",
        sa.Column("snapshot_sha256", sa.String(64), sa.ForeignKey("ett_snapshots.manifest_sha256"), primary_key=True),
        sa.Column("rule_id", sa.String(128), primary_key=True),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("code_valid_from", sa.Date(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_sha256", "code", "code_valid_from"], ["ett_code_versions.snapshot_sha256", "ett_code_versions.code", "ett_code_versions.valid_from"]),
        sa.CheckConstraint("valid_from < valid_to", name="ck_ett_rule_dates"),
    )
    op.create_index("ix_ett_rate_rules_code", "ett_rate_rules", ["code"])


def downgrade() -> None:
    for table in ("ett_rate_rules", "ett_footnotes", "ett_code_versions", "ett_artifacts", "ett_snapshots"):
        op.drop_table(table)
