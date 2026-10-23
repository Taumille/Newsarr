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
    }
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(publications)").fetchall()
        existing = {row[1] for row in rows}
        for name, ddl in additions.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE publications ADD COLUMN {name} {ddl}")


def init_db() -> None:
    from . import models  # noqa: F401  (register mappings)

    Base.metadata.create_all(bind=engine)
    _migrate_publications()
