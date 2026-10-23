"""Keep the queue in sync with the download client."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    DownloadProtocol,
    DownloadRecord,
    Issue,
    IssueStatus,
    TrackedStatus,
    utcnow,
)
from . import settings as settings_service
from .clients import qbittorrent_from_settings
from .library import import_download
from .qbittorrent import QBittorrentError, fetch_torrent_hash, normalize_name
from .torrent import is_info_hash, magnet_info_hash

logger = logging.getLogger(__name__)

ACTIVE = (TrackedStatus.queued, TrackedStatus.downloading)
COMPLETE_STATES = {
    "uploading",
    "stalledUP",
    "forcedUP",
    "pausedUP",
    "completed",
    "queuedUP",
    "checkingUP",
}
FAILED_STATES = {"error", "missingFiles", "unknown"}


async def resolve_record_hash(record: DownloadRecord) -> str:
    """Recover a download's info hash from the release data we stored.

    Used to fix up records that were grabbed before we computed the hash from the
    torrent metadata (their ``client_hash`` may be missing or wrong).
    """
    from_magnet = magnet_info_hash(record.magnet_url)
    if from_magnet:
        return from_magnet
    if record.download_url and record.protocol == DownloadProtocol.torrent:
        return await fetch_torrent_hash(record.download_url)
    return ""


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
        # Fetch the whole torrent list instead of filtering by our stored hash.
        # A missing/wrong hash would make a filtered query return nothing and
        # the download would never be matched (progress stuck at 0%).
        torrents = await client.torrents()
    except QBittorrentError as exc:
        logger.warning("Queue sync skipped: %s", exc)
        return

    by_hash = {(t.get("hash") or "").lower(): t for t in torrents}
    by_name = {normalize_name(t.get("name", "")): t for t in torrents}

    unmatched: list[DownloadRecord] = []

    for record in records:
        torrent = by_hash.get((record.client_hash or "").lower()) if record.client_hash else None
        if torrent is None and record.magnet_url:
            # Self-heal records whose hash was lost: recover it from the magnet.
            recovered = magnet_info_hash(record.magnet_url)
            if recovered:
                torrent = by_hash.get(recovered)
        if torrent is None:
            torrent = by_name.get(normalize_name(record.title))
        if torrent is None and not is_info_hash(record.client_hash or ""):
            # Legacy row with no usable hash: recompute it from the release and
            # store it so we only ever try this once.
            resolved = await resolve_record_hash(record)
            if resolved:
                record.client_hash = resolved
                torrent = by_hash.get(resolved)
        if torrent is None:
            unmatched.append(record)
            continue

        record.client_hash = (torrent.get("hash") or record.client_hash).lower()
        record.progress = int(round(float(torrent.get("progress") or 0) * 100))
        record.save_path = torrent.get("save_path") or record.save_path
        record.content_path = torrent.get("content_path") or record.content_path

        state = torrent.get("state") or ""
        if state in FAILED_STATES:
            record.status = TrackedStatus.failed
            record.error_message = f"qBittorrent state: {state}"
            issue = db.execute(
                select(Issue).where(Issue.download_id == record.id)
            ).scalar_one_or_none()
            if issue is not None and issue.status == IssueStatus.grabbed:
                # Let the issue become searchable/missing again.
                issue.status = IssueStatus.expected
                issue.download_id = None
        elif state in COMPLETE_STATES or record.progress >= 100:
            record.status = TrackedStatus.completed
            record.progress = 100
            record.completed_at = record.completed_at or utcnow()
        else:
            record.status = TrackedStatus.downloading

    db.commit()

    for record in unmatched:
        logger.warning(
            "Queue: no qBittorrent torrent matched %r (stored hash=%r, magnet=%s, "
            "download_url=%s). Client has %d torrent(s): %s",
            record.title,
            record.client_hash,
            bool(record.magnet_url),
            bool(record.download_url),
            len(torrents),
            [t.get("name") for t in torrents][:15],
        )

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
