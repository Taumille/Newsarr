"""Import a completed download into the library folder."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import DownloadRecord, Publication, TrackedStatus, utcnow
from . import settings as settings_service
from .naming import apply_template, slugify

logger = logging.getLogger(__name__)

DOC_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw3", ".cbz", ".cbr", ".djvu", ".zip", ".rar"}


def _iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if root.is_dir():
        return [p for p in root.rglob("*") if p.is_file()]
    return []


def _pick_file(files: list[Path], preferred_format: str) -> Path | None:
    if not files:
        return None

    wanted = preferred_format.lower().strip()
    docs = [f for f in files if f.suffix.lower() in DOC_EXTENSIONS]
    pool = docs or files

    if wanted and wanted != "any":
        ext = f".{wanted}"
        matching = [f for f in pool if f.suffix.lower() == ext]
        if matching:
            pool = matching

    # Fall back to the largest file (covers archive/PDF bundles).
    return max(pool, key=lambda p: p.stat().st_size)


def import_download(db: Session, record: DownloadRecord) -> DownloadRecord:
    """Move the finished file into the library with a tidy name."""
    cfg = settings_service.get_map(db)

    source_root = Path(record.content_path or record.save_path or "")
    files = _iter_files(source_root)
    # If qBittorrent gave us the save dir and it contains subfolders, descend.
    if not files and record.save_path and Path(record.save_path) != source_root:
        files = _iter_files(Path(record.save_path))

    if not files:
        record.status = TrackedStatus.failed
        record.error_message = f"Completed download not found on disk: {source_root}"
        db.commit()
        return record

    publication = (
        db.get(Publication, record.publication_id) if record.publication_id else None
    )
    preferred = publication.preferred_format if publication else "any"
    source = _pick_file(files, preferred)
    if source is None:
        record.status = TrackedStatus.failed
        record.error_message = "No importable file found in the completed download"
        db.commit()
        return record

    root = Path(settings_service.library_root(db))
    subfolder = (publication.folder if publication and publication.folder else "") or (
        slugify(publication.title) if publication else "Unsorted"
    )
    target_dir = root / subfolder
    target_dir.mkdir(parents=True, exist_ok=True)

    date_source = record.publish_date or record.completed_at or utcnow()
    if isinstance(date_source, datetime):
        date_str = date_source.strftime("%Y-%m-%d")
    else:
        date_str = str(date_source)[:10]

    name = apply_template(
        cfg.get("naming_template", "{title} - {date}"),
        title=publication.title if publication else record.title,
        date=date_str,
    )
    target = target_dir / f"{name}{source.suffix.lower()}"
    counter = 1
    while target.exists():
        target = target_dir / f"{name} ({counter}){source.suffix.lower()}"
        counter += 1

    try:
        shutil.move(str(source), str(target))
    except OSError:
        # Cross-device moves are not always supported by rename().
        shutil.copy2(str(source), str(target))
        try:
            source.unlink()
        except OSError:
            pass

    record.imported_path = str(target)
    record.status = TrackedStatus.imported
    record.progress = 100
    record.error_message = ""
    record.completed_at = record.completed_at or utcnow()
    db.commit()
    logger.info("Imported '%s' -> %s", record.title, target)
    return record
