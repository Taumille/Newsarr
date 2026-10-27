"""Grabbing a release into the download client."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    DownloadRecord,
    Issue,
    IssueStatus,
    Publication,
    TrackedStatus,
    utcnow,
)
from ..schemas import Release
from . import settings as settings_service
from .clients import qbittorrent_from_settings
from .qbittorrent import QBittorrentError

logger = logging.getLogger(__name__)


class GrabError(RuntimeError):
    pass


def _link_issue(
    db: Session,
    record: DownloadRecord,
    publication_id: int | None,
    issue_id: int | None,
    release: Release,
) -> None:
    """Attach a grab to a catalog issue (explicit id, else matching date)."""
    issue: Issue | None = None
    if issue_id is not None:
        issue = db.get(Issue, issue_id)
        if issue is not None and issue.publication_id != publication_id:
            issue = None
    if issue is None and publication_id:
        published = release.publish_date
        day = published.date() if published is not None else None
        if day is None:
            return
        issue = db.execute(
            select(Issue).where(
                Issue.publication_id == publication_id, Issue.issue_date == day
            )
        ).scalar_one_or_none()
    if issue is not None:
        issue.status = IssueStatus.grabbed
        issue.download_id = record.id
        issue.file_path = ""


async def grab_release(
    db: Session,
    release: Release,
    publication_id: int | None = None,
    issue_id: int | None = None,
) -> DownloadRecord:
    cfg = settings_service.get_map(db)
    client = qbittorrent_from_settings(cfg)

    save_path = cfg.get("qbittorrent_save_path", "")
    category = cfg.get("qbittorrent_category", "newsarr")

    try:
        info_hash = await client.add(release, save_path=save_path, category=category)
    except QBittorrentError as exc:
        raise GrabError(str(exc)) from exc

    # Never track the same torrent twice. Two records with the same info hash
    # would both import the same content, leaving a duplicate "... (1).pdf".
    if info_hash:
        existing = (
            db.execute(
                select(DownloadRecord).where(
                    DownloadRecord.client_hash == info_hash,
                    DownloadRecord.status != TrackedStatus.failed,
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            if publication_id and existing.publication_id is None:
                existing.publication_id = publication_id
            db.commit()
            logger.info(
                "Release %r is already tracked as download %d (hash %s); not creating a duplicate",
                release.title,
                existing.id,
                info_hash,
            )
            return existing

    if publication_id:
        publication = db.get(Publication, publication_id)
        if publication is not None:
            publication.last_search_at = utcnow()

    record = DownloadRecord(
        publication_id=publication_id,
        title=release.title,
        guid=release.guid,
        indexer=release.indexer,
        indexer_id=release.indexer_id,
        protocol=release.protocol,
        download_url=release.download_url,
        magnet_url=release.magnet_url,
        size=release.size,
        info_url=release.info_url,
        publish_date=release.publish_date,
        client="qBittorrent",
        client_hash=info_hash,
        save_path=save_path,
        status=TrackedStatus.queued,
    )
    db.add(record)
    db.flush()
    _link_issue(db, record, publication_id, issue_id, release)
    db.commit()
    db.refresh(record)
    return record
