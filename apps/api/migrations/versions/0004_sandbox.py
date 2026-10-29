"""sandbox: single-seat demo visits

The public instance runs one visitor at a time. Each turn is a row in ``visits``;
everything it creates is deleted when the turn ends, so the schema needs no
retention policy — the teardown is the policy.

Revision ID: 0004_sandbox
Revises: 0003_multiuser
Create Date: 2026-10-30

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0004_sandbox"
down_revision: str | None = "0003_multiuser"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "visits" in _tables():
        return
    op.create_table(
        "visits",
        sa.Column("id", sa.String(40), primary_key=True),
        # Points at the guest user once active; queued tickets hold a placeholder
        # so promotion is one UPDATE rather than a two-phase commit.
        sa.Column("owner_id", sa.String(60), nullable=False, server_default=""),
        sa.Column("nickname", sa.String(60), nullable=False, server_default=""),
        sa.Column("protocol", sa.String(40), nullable=False, server_default="openai_chat"),
        sa.Column("model_id", sa.String(300), nullable=False, server_default=""),
        sa.Column("base_url", sa.Text(), nullable=False, server_default=""),
        # Sealed under AAD "queue" while waiting, re-sealed under the owner id
        # once the visit is active. A copied value fails to decrypt by design.
        sa.Column("api_key_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("provider_id", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(40), nullable=False, server_default=""),
    )
    op.create_index("ix_visits_owner_id", "visits", ["owner_id"])
    op.create_index("ix_visits_fingerprint", "visits", ["fingerprint"])
    op.create_index("ix_visits_status", "visits", ["status"])
    op.create_index("ix_visits_expires_at", "visits", ["expires_at"])


def downgrade() -> None:
    if "visits" not in _tables():
        return
    for name in (
        "ix_visits_expires_at",
        "ix_visits_status",
        "ix_visits_fingerprint",
        "ix_visits_owner_id",
    ):
        try:
            op.drop_index(name, table_name="visits")
        except Exception:
            pass
    op.drop_table("visits")