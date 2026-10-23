"""Database models.

The vocabulary mirrors Radarr/Sonarr where it makes sense:

* ``Publication`` is the "movie"/"series" you monitor.
* ``DownloadRecord`` is a grabbed release living in the download client queue
  and, once it finishes, the imported library item (the history entry).
* ``AppSetting`` is a small key/value store for user configuration.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class IssueStatus(str, enum.Enum):
    """Lifecycle of a single issue of a publication."""

    # Generated from the publication's schedule but not yet obtained.
    expected = "expected"
    # A download has been grabbed for this issue.
    grabbed = "grabbed"
    # The issue is in the library (imported or found by a folder scan).
    owned = "owned"
    # Explicitly skipped by the user (e.g. an issue that does not exist).
    ignored = "ignored"


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
    # File name of an uploaded cover inside the app's covers folder.
    cover_path: Mapped[str] = mapped_column(String(1000), default="")

    # Publication schedule -----------------------------------------------------
    # One of: irregular, daily, weekly, biweekly, monthly, quarterly.
    frequency: Mapped[str] = mapped_column(String(20), default="irregular")
    # Monday=0 ... Sunday=6. Used by weekly/biweekly schedules.
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # First issue to include when generating the expected-issue calendar.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_search_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    downloads: Mapped[list["DownloadRecord"]] = relationship(
        back_populates="publication", cascade="all, delete-orphan"
    )
    issues: Mapped[list["Issue"]] = relationship(
        back_populates="publication", cascade="all, delete-orphan"
    )

    @property
    def has_cover(self) -> bool:
        """True when a cover image has been uploaded for this publication."""
        return bool(self.cover_path)


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


class Issue(Base):
    """One dated issue of a publication (the "episode" in *arr terms).

    Issues are generated from the publication's schedule (frequency + weekday +
    start date) and then reconciled with reality: a grabbed download marks the
    issue ``grabbed``, an imported/scan-found file marks it ``owned``.
    """

    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("publication_id", "issue_date", name="uq_issue_pub_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    publication: Mapped[Publication] = relationship(back_populates="issues")

    issue_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Optional free-form edition/number label (e.g. "No. 5123").
    label: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus), default=IssueStatus.expected, nullable=False
    )

    # The download currently trying to obtain this issue (if any).
    download_id: Mapped[int | None] = mapped_column(
        ForeignKey("downloads.id", ondelete="SET NULL"), nullable=True
    )
    # Where the owned file lives, when known.
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    """Simple key/value configuration store."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
