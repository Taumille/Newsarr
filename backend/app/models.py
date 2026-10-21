"""Database models.

The vocabulary mirrors Radarr/Sonarr where it makes sense:

* ``Publication`` is the "movie"/"series" you monitor.
* ``DownloadRecord`` is a grabbed release living in the download client queue
  and, once it finishes, the imported library item (the history entry).
* ``AppSetting`` is a small key/value store for user configuration.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    # Stored as naive UTC (SQLite has no timezone type) and serialised as UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TrackedStatus(str, enum.Enum):
    """Lifecycle of a grabbed release."""

    queued = "queued"
    downloading = "downloading"
    completed = "completed"
    imported = "imported"
    failed = "failed"


class DownloadProtocol(str, enum.Enum):
    torrent = "torrent"
    usenet = "usenet"


class Publication(Base):
    """A newspaper or magazine being tracked."""

    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    monitored: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Search hints -----------------------------------------------------------
    # Extra words appended to the title when searching Prowlarr (e.g. "pdf").
    keywords: Mapped[str] = mapped_column(String(500), default="")
    # Comma separated Newznab category ids, e.g. "7010" (Books/Mags) or "7020".
    categories: Mapped[str] = mapped_column(String(200), default="7010,7020,7030")
    language: Mapped[str] = mapped_column(String(20), default="")
    country: Mapped[str] = mapped_column(String(20), default="")
    # Preferred file format: any/pdf/epub/mobi.
    preferred_format: Mapped[str] = mapped_column(String(20), default="any")

    # Library ------------------------------------------------------------------
    # Optional per-publication subfolder (relative to the library root).
    folder: Mapped[str] = mapped_column(String(300), default="")

    # Metadata -----------------------------------------------------------------
    cover_url: Mapped[str] = mapped_column(String(1000), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_search_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    downloads: Mapped[list["DownloadRecord"]] = relationship(
        back_populates="publication", cascade="all, delete-orphan"
    )


class DownloadRecord(Base):
    """A release that has been grabbed into the download client."""

    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(primary_key=True)

    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("publications.id", ondelete="SET NULL"), nullable=True
    )
    publication: Mapped[Publication | None] = relationship(back_populates="downloads")

    # Release identity ---------------------------------------------------------
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    guid: Mapped[str] = mapped_column(String(500), default="")
    indexer: Mapped[str] = mapped_column(String(200), default="")
    indexer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protocol: Mapped[DownloadProtocol] = mapped_column(
        Enum(DownloadProtocol), default=DownloadProtocol.torrent
    )
    download_url: Mapped[str] = mapped_column(Text, default="")
    magnet_url: Mapped[str] = mapped_column(Text, default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    info_url: Mapped[str] = mapped_column(Text, default="")
    publish_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Download client state ----------------------------------------------------
    client: Mapped[str] = mapped_column(String(100), default="qBittorrent")
    client_hash: Mapped[str] = mapped_column(String(200), default="")
    save_path: Mapped[str] = mapped_column(String(1000), default="")
    content_path: Mapped[str] = mapped_column(String(1000), default="")

    status: Mapped[TrackedStatus] = mapped_column(
        Enum(TrackedStatus), default=TrackedStatus.queued
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    error_message: Mapped[str] = mapped_column(Text, default="")

    # Where the file ended up after import.
    imported_path: Mapped[str] = mapped_column(String(1000), default="")

    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSetting(Base):
    """Simple key/value configuration store."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
