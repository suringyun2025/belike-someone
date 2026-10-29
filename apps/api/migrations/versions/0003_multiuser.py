"""multiuser: users, sessions, and tenant ownership columns

Adds the tenant boundary. Existing rows are claimed by the first admin account so
an upgrade from a single-user database does not orphan anyone's work.

Revision ID: 0003_multiuser
Revises: 0002_lease_and_versions
Create Date: 2026-10-30

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0003_multiuser"
down_revision: str | None = "0002_lease_and_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    existing = _tables()

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False, unique=True),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("max_projects", sa.Integer(), nullable=False, server_default="20"),
            sa.Column("max_storage_mb", sa.Integer(), nullable=False, server_default="2048"),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "sessions" not in existing:
        op.create_table(
            "sessions",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(40),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("ip", sa.String(64), nullable=False, server_default=""),
            sa.Column("user_agent", sa.String(400), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
        op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
        op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    # Ownership columns. Nullable on purpose: pre-multiuser rows exist until the
    # backfill below assigns them.
    if "projects" in existing and "owner_id" not in _columns("projects"):
        with op.batch_alter_table("projects") as batch:
            batch.add_column(sa.Column("owner_id", sa.String(40), nullable=True))
            batch.create_foreign_key(
                "fk_projects_owner", "users", ["owner_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_index("ix_projects_owner_id", ["owner_id"])

    if "providers" in existing and "owner_id" not in _columns("providers"):
        with op.batch_alter_table("providers") as batch:
            batch.add_column(sa.Column("owner_id", sa.String(40), nullable=True))
            batch.create_foreign_key(
                "fk_providers_owner", "users", ["owner_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_index("ix_providers_owner_id", ["owner_id"])

    if "jobs" in existing and "owner_id" not in _columns("jobs"):
        with op.batch_alter_table("jobs") as batch:
            batch.add_column(sa.Column("owner_id", sa.String(40), nullable=True))
            batch.create_foreign_key(
                "fk_jobs_owner", "users", ["owner_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_index("ix_jobs_owner_id", ["owner_id"])

    if "audit_events" in existing:
        cols = _columns("audit_events")
        with op.batch_alter_table("audit_events") as batch:
            if "actor_id" not in cols:
                batch.add_column(sa.Column("actor_id", sa.String(40), nullable=True))
                batch.create_index("ix_audit_events_actor_id", ["actor_id"])
            if "ip" not in cols:
                batch.add_column(
                    sa.Column("ip", sa.String(64), nullable=False, server_default="")
                )
            if "user_agent" not in cols:
                batch.add_column(
                    sa.Column("user_agent", sa.String(400), nullable=False, server_default="")
                )

    _backfill()


def _backfill() -> None:
    """Attach pre-existing rows to the first admin.

    Runs only when there is data but no owner: i.e. an upgrade from the
    single-user build. On a fresh database both counts are zero and this is a
    no-op.
    """
    bind = op.get_bind()
    project_count = bind.execute(sa.text("SELECT count(*) FROM projects")).scalar() or 0
    if project_count == 0:
        return
    unowned = bind.execute(
        sa.text("SELECT count(*) FROM projects WHERE owner_id IS NULL")
    ).scalar() or 0
    if unowned == 0:
        return
    admin = bind.execute(
        sa.text("SELECT id FROM users ORDER BY created_at LIMIT 1")
    ).scalar()
    if not admin:
        # No admin yet: leave rows unowned. The startup routine creates a
        # bootstrap admin from env vars and re-runs this claim.
        return
    for table in ("projects", "providers", "jobs"):
        bind.execute(
            sa.text(f"UPDATE {table} SET owner_id = :owner WHERE owner_id IS NULL"),
            {"owner": admin},
        )


def downgrade() -> None:
    existing = _tables()
    # Indexes must go before their columns. SQLite's batch mode rebuilds the
    # table, and it replays index definitions during the copy — an index that
    # references a column already dropped makes that copy fail.
    for table, fk in (
        ("jobs", "fk_jobs_owner"),
        ("providers", "fk_providers_owner"),
        ("projects", "fk_projects_owner"),
    ):
        if table not in existing or "owner_id" not in _columns(table):
            continue
        index_name = f"ix_{table}_owner_id"
        indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
        with op.batch_alter_table(table) as batch:
            try:
                batch.drop_constraint(fk, type_="foreignkey")
            except Exception:
                pass
            batch.drop_column("owner_id")

    if "audit_events" in existing:
        cols = _columns("audit_events")
        indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("audit_events")}
        if "ix_audit_events_actor_id" in indexes:
            op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
        with op.batch_alter_table("audit_events") as batch:
            for column in ("user_agent", "ip", "actor_id"):
                if column in cols:
                    batch.drop_column(column)

    if "sessions" in existing:
        op.drop_table("sessions")
    if "users" in existing:
        op.drop_table("users")