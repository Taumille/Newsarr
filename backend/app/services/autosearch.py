"""Automatic issue searching (the Radarr/Sonarr "RSS + scheduled search" loop).

Two cadences run on top of the same logic:

* **RSS sync** (frequent, e.g. every 30 min) looks only at releases published in
  a short recent window, so new issues are grabbed quickly.
* **Auto search** (less frequent, e.g. every 6 h) does a thorough catch-up for
  anything missed, up to a configurable number of grabs per run.

Both search Prowlarr for each monitored publication, ignore anything already
grabbed, and hand new releases to the download client.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DownloadRecord, Publication, utcnow
from ..schemas import Release
from . import settings as settings_service
from .clients import prowlarr_from_settings
from .grab import GrabError, grab_release
from .issues import sync_calendar
from .prowlarr import ProwlarrClient, ProwlarrError
from .qbittorrent import normalize_name
from .search import build_query, parse_categories

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _title_tokens(title: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (title or "").lower()) if len(t) >= 4]


def _is_relevant(publication: Publication, release: Release) -> bool:
    """Cheap guard against indexers returning unrelated titles."""
    haystack = normalize_name(release.title)
    if not haystack:
        return False
    tokens = _title_tokens(publication.title)
    if not tokens:
        return True
    return any(token in haystack for token in tokens)


def _known_ids(db: Session, publication_id: int) -> tuple[set[str], set[str]]:
    rows = db.execute(
        select(DownloadRecord.guid, DownloadRecord.title).where(
            DownloadRecord.publication_id == publication_id
        )
    ).all()
    guids = {g.lower() for g, _ in rows if g}
    titles = {normalize_name(t) for _, t in rows if t}
    return guids, titles


def _cutoff(db: Session, publication_id: int, fallback: datetime) -> datetime:
    rows = (
        db.execute(
            select(DownloadRecord.publish_date).where(
                DownloadRecord.publication_id == publication_id,
                DownloadRecord.publish_date.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    dates = [_aware(r) for r in rows if r]
    return max(dates) if dates else fallback


def select_new_releases(
    db: Session,
    publication: Publication,
    releases: list[Release],
    cutoff: datetime,
    max_grabs: int,
) -> list[Release]:
    """Pick the not-yet-grabbed, relevant, in-window releases (oldest first)."""
    known_guids, known_titles = _known_ids(db, publication.id)
    preferred = (publication.preferred_format or "any").lower()

    chosen: list[Release] = []
    seen: set[str] = set()
    for release in releases:
        if not _is_relevant(publication, release):
            continue
        if release.guid and release.guid.lower() in known_guids:
            continue
        norm = normalize_name(release.title)
        if norm and norm in known_titles:
            continue
        published = _aware(release.publish_date)
        if published is not None and published < cutoff:
            continue
        key = (release.guid or norm).lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append(release)

    if preferred not in ("", "any"):
        matching = [r for r in chosen if preferred in normalize_name(r.title)]
        if matching:
            chosen = matching

    chosen.sort(key=lambda r: _aware(r.publish_date) or datetime.min.replace(tzinfo=timezone.utc))
    return chosen[:max_grabs]


# --------------------------------------------------------------------------- #
# Per-publication / run-all
# --------------------------------------------------------------------------- #
async def process_publication(
    db: Session,
    publication: Publication,
    cfg: dict[str, object],
    *,
    recent_hours: int | None = None,
    recent_days: int | None = None,
    max_grabs: int = 3,
    client: ProwlarrClient | None = None,
) -> list[DownloadRecord]:
    if not publication.monitored:
        return []

    # Keep the expected-issue calendar in step with the passing weeks/months.
    sync_calendar(db, publication)

    client = client or prowlarr_from_settings(cfg)
    releases = await client.search(
        build_query(publication), categories=parse_categories(publication.categories)
    )

    now = datetime.now(timezone.utc)
    if recent_hours is not None:
        fallback = now - timedelta(hours=recent_hours)
    else:
        fallback = now - timedelta(days=recent_days or 30)
    cutoff = _cutoff(db, publication.id, fallback)

    picks = select_new_releases(db, publication, releases, cutoff, max_grabs)
    grabbed: list[DownloadRecord] = []
    for release in picks:
        try:
            record = await grab_release(db, release, publication.id)
            grabbed.append(record)
            logger.info("Auto-grabbed %r for %r", release.title, publication.title)
        except GrabError as exc:
            logger.warning("Auto-grab failed for %r: %s", release.title, exc)
            break

    publication.last_search_at = utcnow()
    db.commit()
    return grabbed


async def run_for_all(
    db: Session,
    cfg: dict[str, object],
    *,
    recent_hours: int | None = None,
    recent_days: int | None = None,
    max_grabs: int = 3,
) -> dict[str, int]:
    publications = (
        db.execute(select(Publication).where(Publication.monitored.is_(True)))
        .scalars()
        .all()
    )
    if not publications:
        return {"publications": 0, "grabbed": 0}

    try:
        client = prowlarr_from_settings(cfg)
    except ProwlarrError as exc:
        logger.warning("Automatic search skipped: %s", exc)
        return {"publications": 0, "grabbed": 0}

    total = 0
    for publication in publications:
        try:
            total += len(
                await process_publication(
                    db,
                    publication,
                    cfg,
                    recent_hours=recent_hours,
                    recent_days=recent_days,
                    max_grabs=max_grabs,
                    client=client,
                )
            )
        except ProwlarrError as exc:
            logger.warning("Search failed for %r: %s", publication.title, exc)

    logger.info("Automatic search: %d publication(s), %d grabbed", len(publications), total)
    return {"publications": len(publications), "grabbed": total}


# --------------------------------------------------------------------------- #
# Entry points used by the scheduler / API
# --------------------------------------------------------------------------- #
async def run_rss_sync(db: Session) -> dict[str, int]:
    cfg = settings_service.get_map(db)
    return await run_for_all(
        db,
        cfg,
        recent_hours=settings_service.as_int(cfg, "rss_recent_hours", 72),
        max_grabs=settings_service.as_int(cfg, "auto_search_max_grabs", 3),
    )


async def run_auto_search(db: Session) -> dict[str, int]:
    cfg = settings_service.get_map(db)
    return await run_for_all(
        db,
        cfg,
        recent_days=settings_service.as_int(cfg, "auto_search_recent_days", 30),
        max_grabs=settings_service.as_int(cfg, "auto_search_max_grabs", 3),
    )


async def rss_once() -> None:
    db = SessionLocal()
    try:
        await run_rss_sync(db)
    finally:
        db.close()


async def autosearch_once() -> None:
    db = SessionLocal()
    try:
        await run_auto_search(db)
    finally:
        db.close()
