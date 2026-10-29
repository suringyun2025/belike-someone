from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

logger = logging.getLogger("distill.db")


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        # Server-backed databases need a real pool; SQLite defaults are wrong here.
        kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_recycle": 1800})
    return kwargs


engine = create_engine(settings.database_url, **_engine_kwargs())

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
        try:
            import sqlite_vec

            dbapi_connection.enable_load_extension(True)
            sqlite_vec.load(dbapi_connection)
            dbapi_connection.enable_load_extension(False)
        except Exception as exc:  # pragma: no cover - optional extension
            logger.debug("sqlite-vec unavailable: %s", exc)


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create or migrate the schema.

    Migrations run first when Alembic is available; ``create_all`` remains the
    fallback so a fresh checkout still works without extra setup. Both paths are
    idempotent.
    """
    from . import models  # noqa: F401  (register mappers)

    if not run_migrations():
        Base.metadata.create_all(bind=engine)
        logger.info("schema ensured via create_all")
    try:
        from .vector_store import ensure_vector_schema

        ensure_vector_schema()
    except Exception as exc:  # pragma: no cover - optional extension
        logger.warning("vector schema unavailable: %s", exc)


def run_migrations() -> bool:
    """Apply Alembic migrations. Returns True when migrations ran.

    Handles the upgrade path from 0.1.0, which created the schema with
    ``create_all`` and therefore has tables but no ``alembic_version`` row.
    Running the baseline migration against such a database would fail with
    "table already exists", so we detect that state and stamp it instead.
    """
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:  # pragma: no cover - alembic is an optional dep
        return False

    from .config import ROOT_DIR

    ini = ROOT_DIR / "apps" / "api" / "alembic.ini"
    script_location = ROOT_DIR / "apps" / "api" / "migrations"
    if not ini.exists() or not script_location.exists():
        return False
    try:
        config = Config(str(ini))
        config.set_main_option("script_location", str(script_location))
        config.set_main_option("sqlalchemy.url", settings.database_url)
        if _needs_baseline_stamp():
            logger.info("legacy schema detected; stamping baseline revision")
            command.stamp(config, "0001_baseline")
        command.upgrade(config, "head")
        logger.info("schema migrated to head")
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("migration failed, falling back to create_all: %s", exc)
        return False


def _needs_baseline_stamp() -> bool:
    """True when application tables exist but Alembic has no recorded revision."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not tables or "projects" not in tables:
        return False
    if "alembic_version" not in tables:
        # Tables exist and Alembic has never run: this is a 0.1.0 database.
        return True
    with engine.connect() as connection:
        row = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
    # An empty alembic_version table means Alembic created the bookkeeping table
    # but never recorded a revision for the pre-existing schema.
    return row is None


def healthcheck() -> dict:
    """Return a uniform ``{status, ...}`` shape so clients can render any check."""
    from sqlalchemy import text

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "dialect": engine.dialect.name}