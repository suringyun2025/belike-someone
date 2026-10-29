"""add job lease fencing, usage totals and skill version history

Upgrades a 0.1.0 database in place. The baseline migration assumes a fresh
schema, so this second revision carries the additive changes that a legacy
``create_all`` database does not have:

* ``jobs.worker_id`` / ``lease_expires_at`` / ``lease_epoch`` / ``usage``
  (multi-worker claiming with fencing tokens)
* ``skill_versions`` (immutable snapshots for diff and rollback)

All operations are guards so the revision is idempotent: a fresh database that
already ran the baseline plus this revision, and a stamped legacy database,
both converge to the same shape.

Revision ID: 0002_lease_and_versions
Revises: 0001_baseline
Create Date: 2026-10-30

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0002_lease_and_versions"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    job_columns = _columns("jobs")
    existing_tables = _tables()

    if "jobs" in existing_tables:
        # batch_alter_table 让 SQLite 也能加列（它不支持原生 ADD CONSTRAINT，
        # 但纯加列可以直接 ALTER，batch 模式会选最优路径）。
        with op.batch_alter_table("jobs") as batch:
            if "worker_id" not in job_columns:
                batch.add_column(
                    sa.Column("worker_id", sa.String(120), nullable=False, server_default="")
                )
            if "lease_expires_at" not in job_columns:
                batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
            if "lease_epoch" not in job_columns:
                batch.add_column(
                    sa.Column("lease_epoch", sa.Integer(), nullable=False, server_default="0")
                )
            if "usage" not in job_columns:
                batch.add_column(sa.Column("usage", sa.JSON(), nullable=False, server_default="{}"))

    if "skill_versions" not in existing_tables:
        op.create_table(
            "skill_versions",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("skill_id", sa.String(40), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(40), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("files", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("claim_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("job_id", sa.String(40), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])
        op.create_index("ix_skill_versions_project_id", "skill_versions", ["project_id"])
        op.create_index("ix_skill_versions_content_hash", "skill_versions", ["content_hash"])
        op.create_index(
            "ix_skill_versions_skill_version", "skill_versions", ["skill_id", "version"]
        )

    # The lease index is only useful for the recovery sweep; create it explicitly
    # because batch_alter_table on SQLite rebuilds the table and drops indexes.
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("jobs")} if "jobs" in existing_tables else set()
    if "jobs" in existing_tables and "ix_jobs_lease_expires_at" not in indexes:
        op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])


def downgrade() -> None:
    existing_tables = _tables()
    if "skill_versions" in existing_tables:
        op.drop_table("skill_versions")
    if "jobs" in existing_tables:
        job_columns = _columns("jobs")
        # The index must go before the column, otherwise batch mode rebuilds the
        # table and fails recreating an index whose column no longer exists.
        indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("jobs")}
        if "ix_jobs_lease_expires_at" in indexes:
            op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")
        with op.batch_alter_table("jobs") as batch:
            for column in ("usage", "lease_epoch", "lease_expires_at", "worker_id"):
                if column in job_columns:
                    batch.drop_column(column)