"""Migration path tests.

The upgrade from 0.1.0 is the highest-risk code path in a release: it runs once,
on a database that already contains the user's work, and a failure there is not
recoverable by re-running the app. These tests exercise it explicitly.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

API_DIR = Path(__file__).resolve().parents[1]
BASELINE = "0001_baseline"
HEAD = "0004_sandbox"


def _config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _make_legacy_db(db_path: Path) -> None:
    """Recreate a 0.1.0 database: tables, data, no alembic_version."""
    config = _config(db_path)
    command.upgrade(config, BASELINE)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        # Drop the bookkeeping table to imitate create_all() output.
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(
            text(
                "INSERT INTO projects (id, name, codename, purpose, authorization_note, "
                "prohibited_uses, target_platforms, status, created_at, updated_at) "
                "VALUES ('prj_legacy', '遗留项目', 'legacy', '', '', '', '[]', 'active', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        # The baseline already includes the new columns, so remove them to make
        # the fixture match a real 0.1.0 schema.
        for column in ("worker_id", "lease_expires_at", "lease_epoch", "usage"):
            try:
                connection.execute(text(f"ALTER TABLE jobs DROP COLUMN {column}"))
            except Exception:
                pass
        connection.execute(text("DROP TABLE IF EXISTS skill_versions"))
    engine.dispose()


def test_baseline_from_empty_database(tmp_path):
    db_path = tmp_path / "fresh.db"
    command.upgrade(_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert {"projects", "chunks", "claims", "jobs", "skill_versions"} <= tables
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == HEAD
    engine.dispose()


def test_legacy_database_can_be_stamped_and_upgraded(tmp_path):
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)

    config = _config(db_path)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.connect() as connection:
        assert "alembic_version" not in set(inspect(engine).get_table_names())
        assert connection.execute(text("SELECT count(*) FROM projects")).scalar() == 1
    engine.dispose()

    # This mirrors what app.db.run_migrations() does on startup.
    command.stamp(config, BASELINE)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    columns = {column["name"] for column in inspect(engine).get_columns("jobs")}
    assert {"worker_id", "lease_expires_at", "lease_epoch", "usage"} <= columns
    assert "skill_versions" in set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        # The whole point: existing user data survives the upgrade.
        assert connection.execute(text("SELECT count(*) FROM projects")).scalar() == 1
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
        )
    engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    db_path = tmp_path / "twice.db"
    config = _config(db_path)
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # must be a no-op, not an error

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
    engine.dispose()


def test_downgrade_removes_lease_columns(tmp_path):
    db_path = tmp_path / "down.db"
    config = _config(db_path)
    command.upgrade(config, "head")
    command.downgrade(config, BASELINE)

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    columns = {column["name"] for column in inspect(engine).get_columns("jobs")}
    assert "lease_epoch" not in columns
    assert "skill_versions" not in set(inspect(engine).get_table_names())
    engine.dispose()