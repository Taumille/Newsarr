"""Grabbing a release into the download client."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import DownloadRecord, Publication, TrackedStatus, utcnow
from ..schemas import Release
from . import settings as settings_service
from .clients import qbittorrent_from_settings
from .qbittorrent import QBittorrentError


class GrabError(RuntimeError):
    pass


async def grab_release(
    db: Session, release: Release, publication_id: int | None = None
) -> DownloadRecord:
    cfg = settings_service.get_map(db)
    client = qbittorrent_from_settings(cfg)

    save_path = cfg.get("qbittorrent_save_path", "")
    category = cfg.get("qbittorrent_category", "newsarr")

    try:
        info_hash = await client.add(release, save_path=save_path, category=category)
    except QBittorrentError as exc:
        raise GrabError(str(exc)) from exc

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
    db.commit()
    db.refresh(record)
    return record
