"""Keep the queue in sync with the download client."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DownloadRecord, TrackedStatus, utcnow
from . import settings as settings_service
from .clients import qbittorrent_from_settings
from .library import import_download
from .qbittorrent import QBittorrentError, normalize_name

logger = logging.getLogger(__name__)

ACTIVE = (TrackedStatus.queued, TrackedStatus.downloading)
COMPLETE_STATES = {"uploading", "stalledUP", "forcedUP", "pausedUP", "completed", "queuedUP", "checkingUP"}
FAILED_STATES = {"error", "missingFiles", "unknown"}


async def sync_queue(db: Session) -> None:
    """Refresh active downloads and import anything that finished."""
    cfg = settings_service.get_map(db)
    records = (
        db.execute(select(DownloadRecord).where(DownloadRecord.status.in_(ACTIVE)))
        .scalars()
        .all()
    )
    if not records:
        return

    try:
        client = qbittorrent_from_settings(cfg)
        hashes = [r.client_hash for r in records if r.client_hash]
        torrents = await client.torrents(hashes or None)
    except QBittorrentError as exc:
        logger.warning("Queue sync skipped: %s", exc)
        return

    by_hash = {(t.get("hash") or "").lower(): t for t in torrents}
    by_name = {normalize_name(t.get("name", "")): t for t in torrents}

    for record in records:
        torrent = by_hash.get((record.client_hash or "").lower())
        if torrent is None:
            torrent = by_name.get(normalize_name(record.title))
        if torrent is None:
            continue

        record.client_hash = (torrent.get("hash") or record.client_hash).lower()
        record.progress = int(round(float(torrent.get("progress") or 0) * 100))
        record.save_path = torrent.get("save_path") or record.save_path
        record.content_path = torrent.get("content_path") or record.content_path

        state = torrent.get("state") or ""
        if state in FAILED_STATES:
            record.status = TrackedStatus.failed
            record.error_message = f"qBittorrent state: {state}"
        elif state in COMPLETE_STATES or record.progress >= 100:
            record.status = TrackedStatus.completed
            record.progress = 100
            record.completed_at = record.completed_at or utcnow()
        else:
            record.status = TrackedStatus.downloading
    db.commit()

    completed = (
        db.execute(select(DownloadRecord).where(DownloadRecord.status == TrackedStatus.completed))
        .scalars()
        .all()
    )
    for record in completed:
        try:
            import_download(db, record)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Import failed for %s", record.title)
            record.status = TrackedStatus.failed
            record.error_message = "Import failed -- see logs"
            db.commit()


async def sync_once() -> None:
    """One pass, managing its own session (used by the background loop)."""
    db = SessionLocal()
    try:
        await sync_queue(db)
    finally:
        db.close()
