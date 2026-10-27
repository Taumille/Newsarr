"""SQLAlchemy engine / session setup (SQLite by default)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    f"sqlite:///{settings.database_path}",
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_publications() -> None:
    """Add columns introduced after the first release (SQLite has no Alembic).

    ``create_all`` only creates missing *tables*, so existing databases need an
    explicit ``ALTER TABLE`` for new publication columns. Adding columns is
    backwards compatible and idempotent.
    """
    additions = {
        "frequency": "VARCHAR(20) NOT NULL DEFAULT 'irregular'",
        "weekday": "INTEGER",
        "start_date": "DATE",
        "cover_path": "VARCHAR(1000) NOT NULL DEFAULT ''",
        "exclude_keywords": "VARCHAR(500) NOT NULL DEFAULT ''",
    }
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(publications)").fetchall()
        existing = {row[1] for row in rows}
        for name, ddl in additions.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE publications ADD COLUMN {name} {ddl}")


def _migrate_downloads() -> None:
    """Add a partial unique index on ``downloads.client_hash``.

    SQLite treats NULLs as distinct and empty strings as a value, so the index
    is restricted to non-empty hashes (usenet grabs have no hash). If an older
    database already contains duplicate hashes the index cannot be created; we
    log and carry on, since ``grab_release`` also guards against duplicates.
    """
    with engine.begin() as conn:
        try:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_downloads_client_hash "
                "ON downloads (client_hash) WHERE client_hash IS NOT NULL AND client_hash <> ''"
            )
        except Exception as exc:  # pragma: no cover - depends on existing data
            import logging

            logging.getLogger(__name__).warning(
                "Could not create unique index on downloads.client_hash (duplicates "
                "already present?): %s",
                exc,
            )


def init_db() -> None:
    from . import models  # noqa: F401  (register mappings)

    Base.metadata.create_all(bind=engine)
    _migrate_publications()
    _migrate_downloads()
