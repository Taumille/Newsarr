"""Issue catalog: schedule generation, owned/missing tracking and gap search.

A ``Publication`` is the newspaper/magazine title; an ``Issue`` is one dated
edition of it. Issues are generated from a simple schedule (daily, weekly on a
given weekday, monthly, …) starting at ``Publication.start_date``. They then
move through:

    expected ──grab──▶ grabbed ──import──▶ owned
        │                                   ▲
        └──────────── folder scan ──────────┘

``missing`` is not a stored state: an issue that is still ``expected`` but whose
date has passed is counted as missing.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import DownloadRecord, Issue, IssueStatus, Publication
from ..schemas import IssueSummary, Release
from . import settings as settings_service
from .clients import prowlarr_from_settings
from .grab import GrabError, grab_release
from .naming import slugify
from .search import build_query, parse_categories

logger = logging.getLogger(__name__)

FREQUENCIES = ("irregular", "daily", "weekly", "biweekly", "monthly", "quarterly")
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Generate at most this many dates in one pass (a daily paper since 2000 is ~9k).
MAX_GENERATED = 6000

SCAN_EXTENSIONS = {
    ".pdf",
    ".epub",
    ".mobi",
    ".azw3",
    ".cbz",
    ".cbr",
    ".djvu",
    ".zip",
    ".rar",
}

# Date spellings commonly found in release/file names.
_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)"),
)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}

_MONTH_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th|er)?\s+([a-zéûôà]+)\.?\s+(\d{4})(?!\d)", re.IGNORECASE
)


# --------------------------------------------------------------------------- #
# Date / schedule helpers
# --------------------------------------------------------------------------- #
def _as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def generate_issue_dates(
    frequency: str,
    weekday: int | None,
    start: date | None,
    end: date | None = None,
) -> list[date]:
    """Return every scheduled issue date in ``[start, end]`` (oldest first)."""
    if not start:
        return []
    end = end or date.today()
    if end < start:
        return []

    frequency = (frequency or "irregular").lower()
    dates: list[date] = []
    if frequency == "daily":
        current = start
        while current <= end and len(dates) < MAX_GENERATED:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    if frequency in ("weekly", "biweekly"):
        if weekday is None or not 0 <= weekday <= 6:
            weekday = start.weekday()
        current = start + timedelta(days=(weekday - start.weekday()) % 7)
        step = timedelta(days=7 if frequency == "weekly" else 14)
        while current <= end and len(dates) < MAX_GENERATED:
            dates.append(current)
            current += step
        return dates

    if frequency in ("monthly", "quarterly"):
        step = 1 if frequency == "monthly" else 3
        year, month = start.year, start.month
        while len(dates) < MAX_GENERATED:
            day = min(start.day, calendar.monthrange(year, month)[1])
            current = date(year, month, day)
            if current > end:
                break
            if current >= start:
                dates.append(current)
            month += step
            while month > 12:
                month -= 12
                year += 1
        return dates

    return []


def effective_weekday(publication: Publication) -> int | None:
    if publication.weekday is not None and 0 <= publication.weekday <= 6:
        return publication.weekday
    if publication.start_date is not None:
        return publication.start_date.weekday()
    return None


def schedule_label(publication: Publication) -> str:
    """Human-readable summary, e.g. "weekly on Wednesday"."""
    frequency = (publication.frequency or "irregular").lower()
    if frequency == "irregular":
        return "irregular"
    if frequency in ("weekly", "biweekly"):
        weekday = effective_weekday(publication)
        suffix = f" on {WEEKDAY_NAMES[weekday]}" if weekday is not None else ""
        return f"{frequency}{suffix}"
    return frequency


# --------------------------------------------------------------------------- #
# Calendar maintenance
# --------------------------------------------------------------------------- #
def sync_calendar(
    db: Session, publication: Publication, end: date | None = None
) -> dict[str, int]:
    """Create newly-scheduled issues and prune stale *expected* ones.

    Owned, grabbed and ignored issues are never deleted: they represent real
    files or deliberate decisions.
    """
    dates = generate_issue_dates(
        publication.frequency,
        effective_weekday(publication),
        publication.start_date,
        end,
    )
    if not dates:
        return {"added": 0, "removed": 0, "total": 0}

    existing = {
        issue.issue_date: issue
        for issue in db.execute(
            select(Issue).where(Issue.publication_id == publication.id)
        ).scalars()
    }
    wanted = set(dates)
    added = 0
    removed = 0

    for day in dates:
        if day not in existing:
            db.add(Issue(publication_id=publication.id, issue_date=day))
            added += 1

    for day, issue in existing.items():
        if (
            day not in wanted
            and issue.status == IssueStatus.expected
            and issue.download_id is None
        ):
            db.delete(issue)
            removed += 1

    db.commit()
    if added or removed:
        logger.info(
            "Issue calendar for %r: +%d / -%d (total %d)",
            publication.title,
            added,
            removed,
            len(wanted),
        )
    return {"added": added, "removed": removed, "total": len(wanted)}


def find_issue(db: Session, publication_id: int, day: date | None) -> Issue | None:
    if day is None:
        return None
    return db.execute(
        select(Issue).where(
            Issue.publication_id == publication_id, Issue.issue_date == day
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #
def _summary_from_row(row) -> IssueSummary:
    _, total, owned, missing, upcoming, grabbed, ignored = row
    return IssueSummary(
        total=int(total or 0),
        owned=int(owned or 0),
        missing=int(missing or 0),
        upcoming=int(upcoming or 0),
        grabbed=int(grabbed or 0),
        ignored=int(ignored or 0),
    )


def _summary_query():
    today = date.today()
    return select(
        Issue.publication_id,
        func.count(Issue.id),
        func.sum(case((Issue.status == IssueStatus.owned, 1), else_=0)),
        func.sum(
            case(
                (
                    (Issue.status == IssueStatus.expected) & (Issue.issue_date <= today),
                    1,
                ),
                else_=0,
            )
        ),
        func.sum(
            case(
                (
                    (Issue.status == IssueStatus.expected) & (Issue.issue_date > today),
                    1,
                ),
                else_=0,
            )
        ),
        func.sum(case((Issue.status == IssueStatus.grabbed, 1), else_=0)),
        func.sum(case((Issue.status == IssueStatus.ignored, 1), else_=0)),
    )


def summaries(db: Session, publication_ids: list[int]) -> dict[int, IssueSummary]:
    if not publication_ids:
        return {}
    rows = db.execute(
        _summary_query()
        .where(Issue.publication_id.in_(publication_ids))
        .group_by(Issue.publication_id)
    ).all()
    return {row[0]: _summary_from_row(row) for row in rows}


def summary_for(db: Session, publication_id: int) -> IssueSummary:
    row = db.execute(
        _summary_query().where(Issue.publication_id == publication_id)
    ).first()
    if row is None:
        return IssueSummary()
    return _summary_from_row(row)


# --------------------------------------------------------------------------- #
# Status transitions
# --------------------------------------------------------------------------- #
def mark_grabbed(db: Session, issue: Issue, record: DownloadRecord) -> None:
    issue.status = IssueStatus.grabbed
    issue.download_id = record.id
    issue.file_path = ""


def record_owned(
    db: Session,
    record: DownloadRecord,
    file_path: str | Path,
    when: date | datetime | None = None,
) -> Issue | None:
    """Mark the issue matching an imported/scan-found file as owned."""
    if not record.publication_id:
        return None
    day = _as_date(when) or _as_date(record.publish_date) or date.today()
    issue = find_issue(db, record.publication_id, day)
    if issue is None:
        issue = Issue(publication_id=record.publication_id, issue_date=day)
        db.add(issue)
    issue.status = IssueStatus.owned
    issue.file_path = str(file_path)
    issue.download_id = record.id
    return issue


def release_issue_date(release: Release) -> date | None:
    """Best-effort issue date for a release.

    Prefer a date written in the title (that is the issue date); fall back to
    the indexer's publish date, which may instead be an upload date.
    """
    from_title = extract_date_from_filename(release.title)
    if from_title is not None:
        return from_title
    if release.publish_date is not None:
        published = release.publish_date
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published.astimezone(timezone.utc).date()
    return None


def extract_date_from_filename(value: str) -> date | None:
    """Extract a plausible issue date from a title or file name."""
    text = value or ""

    for pattern in _DATE_PATTERNS[:2]:
        for match in pattern.finditer(text):
            groups = match.groups()
            try:
                if len(groups[0]) == 4:  # YYYY-MM-DD
                    year, month, day = (int(g) for g in groups)
                else:  # DD-MM-YYYY
                    day, month, year = (int(g) for g in groups)
                return date(year, month, day)
            except ValueError:
                continue

    match = _DATE_PATTERNS[2].search(text)
    if match:
        try:
            year, month, day = (int(g) for g in match.groups())
            return date(year, month, day)
        except ValueError:
            pass

    match = _MONTH_DATE_RE.search(text)
    if match:
        month = _MONTHS.get(match.group(2).lower().rstrip("."))
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                pass
    return None


def release_matches_issue(release: Release, issue_date: date, tolerance: int = 1) -> bool:
    release_date = release_issue_date(release)
    if release_date is None:
        return False
    return abs((release_date - issue_date).days) <= tolerance


def releases_for_issue(releases: list[Release], issue_date: date) -> list[Release]:
    matched = [r for r in releases if release_matches_issue(r, issue_date)]
    matched.sort(key=lambda r: r.publish_date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return matched


# --------------------------------------------------------------------------- #
# Library folder scanning
# --------------------------------------------------------------------------- #
def _publication_folder(db: Session, publication: Publication) -> Path | None:
    root = Path(settings_service.library_root(db))
    subfolder = (publication.folder or "").strip() or slugify(publication.title)
    folder = root / subfolder
    return folder if folder.exists() else None


def scan_library(db: Session, publication: Publication) -> dict[str, int]:
    """Mark issues as owned by looking for dated files in the publication folder."""
    folder = _publication_folder(db, publication)
    if folder is None:
        return {"scanned": 0, "matched": 0, "owned": 0}

    files = [
        p
        for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in SCAN_EXTENSIONS
    ]
    matched = 0
    for path in files:
        day = extract_date_from_filename(path.name)
        if day is None:
            continue
        issue = find_issue(db, publication.id, day)
        if issue is None:
            issue = Issue(publication_id=publication.id, issue_date=day)
            db.add(issue)
        issue.status = IssueStatus.owned
        issue.file_path = str(path)
        issue.download_id = None
        matched += 1

    db.commit()
    summary = summary_for(db, publication.id)
    logger.info(
        "Scanned %r: %d file(s), %d dated issue(s) matched",
        publication.title,
        len(files),
        matched,
    )
    return {"scanned": len(files), "matched": matched, "owned": summary.owned}


# --------------------------------------------------------------------------- #
# Gap search
# --------------------------------------------------------------------------- #
def _pick_candidate(candidates: list[Release], publication: Publication) -> Release | None:
    if not candidates:
        return None
    preferred = (publication.preferred_format or "any").lower()

    def score(release: Release) -> tuple[int, int, float]:
        format_hit = 1 if preferred not in ("", "any") and preferred in release.title.lower() else 0
        seeders = release.seeders or 0
        published = release.publish_date.timestamp() if release.publish_date else 0.0
        return (format_hit, seeders, published)

    return max(candidates, key=score)


async def search_for_issue(
    db: Session,
    publication: Publication,
    issue: Issue,
) -> list[Release]:
    """Search Prowlarr for one dated issue and return date-matched releases."""
    cfg = settings_service.get_map(db)
    client = prowlarr_from_settings(cfg)
    categories = parse_categories(publication.categories)
    base = build_query(publication)

    # Try date-qualified queries first; fall back to the plain title query.
    date_forms = (
        issue.issue_date.strftime("%Y-%m-%d"),
        issue.issue_date.strftime("%Y%m%d"),
        issue.issue_date.strftime("%d-%m-%Y"),
    )
    for extra in date_forms:
        releases = await client.search(build_query(publication, extra), categories=categories)
        matched = releases_for_issue(releases, issue.issue_date)
        if matched:
            return matched

    releases = await client.search(base, categories=categories)
    return releases_for_issue(releases, issue.issue_date)


async def search_missing(
    db: Session,
    publication: Publication,
    max_grabs: int = 10,
) -> dict[str, int]:
    """Find and grab releases for missing issues (newest gaps first)."""
    missing = (
        db.execute(
            select(Issue)
            .where(
                Issue.publication_id == publication.id,
                Issue.status == IssueStatus.expected,
                Issue.issue_date <= date.today(),
            )
            .order_by(Issue.issue_date.desc())
        )
        .scalars()
        .all()
    )
    if not missing:
        return {"missing": 0, "searched": 0, "grabbed": 0}

    cfg = settings_service.get_map(db)
    client = prowlarr_from_settings(cfg)
    releases = await client.search(
        build_query(publication), categories=parse_categories(publication.categories)
    )

    grabbed = 0
    failures = 0
    used: set[str] = set()
    for issue in missing:
        if grabbed >= max_grabs:
            break
        candidates = [
            release
            for release in releases_for_issue(releases, issue.issue_date)
            if (release.guid or release.title) not in used
        ]
        candidate = _pick_candidate(candidates, publication)
        if candidate is None:
            continue
        used.add(candidate.guid or candidate.title)
        try:
            await grab_release(db, candidate, publication.id, issue_id=issue.id)
            grabbed += 1
            logger.info(
                "Gap search grabbed %r for %r %s",
                candidate.title,
                publication.title,
                issue.issue_date,
            )
        except GrabError as exc:
            failures += 1
            logger.warning("Gap search grab failed for %r: %s", candidate.title, exc)
            # A broken release should not stop us looking at other dates, but
            # stop after a few failures (usually the client is unreachable).
            if failures >= 3:
                break

    return {"missing": len(missing), "searched": len(missing), "grabbed": grabbed}
