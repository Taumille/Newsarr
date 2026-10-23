"""Publication CRUD + per-publication search."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings as bootstrap
from ..database import get_db
from ..models import Publication, utcnow
from ..schemas import (
    DownloadRecordSchema,
    IssueSummary,
    Publication as PublicationSchema,
    PublicationCreate,
    PublicationUpdate,
    SearchResponse,
)
from ..services import settings as settings_service
from ..services.autosearch import process_publication
from ..services.clients import prowlarr_from_settings
from ..services.issues import summaries, summary_for, sync_calendar
from ..services.naming import slugify
from ..services.prowlarr import ProwlarrError
from ..services.search import build_query, parse_categories

router = APIRouter(prefix="/api/v1/publications", tags=["publications"])

COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
COVER_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_COVER_BYTES = 10 * 1024 * 1024


def _covers_dir() -> Path:
    folder = bootstrap.data_dir / "covers"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _remove_cover_files(publication_id: int) -> None:
    for path in _covers_dir().glob(f"{publication_id}.*"):
        try:
            path.unlink()
        except OSError:
            pass


def _serialize(publication: Publication, summary: IssueSummary | None = None) -> PublicationSchema:
    summary = summary or IssueSummary()
    model = PublicationSchema.model_validate(publication)
    return model.model_copy(
        update={
            "issue_total": summary.total,
            "issue_owned": summary.owned,
            "issue_missing": summary.missing,
            "issue_upcoming": summary.upcoming,
        }
    )


def _refresh_calendar(db: Session, publication: Publication) -> None:
    if publication.start_date and (publication.frequency or "irregular") != "irregular":
        sync_calendar(db, publication)


@router.get("", response_model=list[PublicationSchema])
def list_publications(
    monitored: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    stmt = select(Publication).order_by(Publication.title)
    if monitored is not None:
        stmt = stmt.where(Publication.monitored == monitored)
    publications = db.execute(stmt).scalars().all()
    stats = summaries(db, [p.id for p in publications])
    return [_serialize(p, stats.get(p.id)) for p in publications]


@router.post("", response_model=PublicationSchema, status_code=201)
def create_publication(payload: PublicationCreate, db: Session = Depends(get_db)):
    existing = db.execute(
        select(Publication).where(Publication.title.ilike(payload.title))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A publication with that title already exists")

    publication = Publication(**payload.model_dump())
    publication.slug = slugify(payload.title)
    db.add(publication)
    db.commit()
    db.refresh(publication)
    _refresh_calendar(db, publication)
    return _serialize(publication, summary_for(db, publication.id))


def _get_or_404(db: Session, publication_id: int) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return publication


@router.get("/{publication_id}", response_model=PublicationSchema)
def get_publication(publication_id: int, db: Session = Depends(get_db)):
    publication = _get_or_404(db, publication_id)
    return _serialize(publication, summary_for(db, publication.id))


@router.put("/{publication_id}", response_model=PublicationSchema)
def update_publication(
    publication_id: int, payload: PublicationUpdate, db: Session = Depends(get_db)
):
    publication = _get_or_404(db, publication_id)
    data = payload.model_dump(exclude_unset=True)
    schedule_changed = False
    for key, value in data.items():
        if value is None and key not in ("start_date", "weekday"):
            continue
        if key in ("start_date", "weekday", "frequency"):
            schedule_changed = True
        setattr(publication, key, value)
    if payload.title:
        publication.slug = slugify(payload.title)
    db.commit()
    db.refresh(publication)
    if schedule_changed:
        _refresh_calendar(db, publication)
    return _serialize(publication, summary_for(db, publication.id))


@router.delete("/{publication_id}", status_code=204)
def delete_publication(publication_id: int, db: Session = Depends(get_db)):
    publication = _get_or_404(db, publication_id)
    _remove_cover_files(publication_id)
    db.delete(publication)
    db.commit()


# --------------------------------------------------------------------------- #
# Cover images
# --------------------------------------------------------------------------- #
@router.post("/{publication_id}/cover", response_model=PublicationSchema)
async def upload_cover(
    publication_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    publication = _get_or_404(db, publication_id)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in COVER_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image type. Use JPG, PNG, WebP or GIF.",
        )

    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(blob) > MAX_COVER_BYTES:
        raise HTTPException(status_code=413, detail="Cover images must be under 10 MB")

    _remove_cover_files(publication_id)
    filename = f"{publication_id}{extension}"
    (_covers_dir() / filename).write_bytes(blob)
    publication.cover_path = filename
    db.commit()
    db.refresh(publication)
    return _serialize(publication, summary_for(db, publication.id))


@router.delete("/{publication_id}/cover", response_model=PublicationSchema)
def delete_cover(publication_id: int, db: Session = Depends(get_db)):
    publication = _get_or_404(db, publication_id)
    _remove_cover_files(publication_id)
    publication.cover_path = ""
    db.commit()
    db.refresh(publication)
    return _serialize(publication, summary_for(db, publication.id))


@router.get("/{publication_id}/cover")
def get_cover(publication_id: int, db: Session = Depends(get_db)):
    publication = _get_or_404(db, publication_id)
    if not publication.cover_path:
        raise HTTPException(status_code=404, detail="No cover uploaded")
    path = _covers_dir() / publication.cover_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Cover file is missing")
    media_type = COVER_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "max-age=3600"})


@router.post("/{publication_id}/search", response_model=SearchResponse)
async def search_publication(
    publication_id: int,
    extra: str = Query(default=""),
    db: Session = Depends(get_db),
):
    publication = _get_or_404(db, publication_id)
    cfg = settings_service.get_map(db)
    try:
        client = prowlarr_from_settings(cfg)
        releases = await client.search(
            build_query(publication, extra),
            categories=parse_categories(publication.categories),
        )
    except ProwlarrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    publication.last_search_at = utcnow()
    db.commit()
    return SearchResponse(query=build_query(publication, extra), releases=releases)


@router.post("/{publication_id}/auto-search", response_model=list[DownloadRecordSchema])
async def auto_search_publication(
    publication_id: int,
    db: Session = Depends(get_db),
):
    """Immediately run the automatic search for one publication and grab new issues."""
    publication = _get_or_404(db, publication_id)
    cfg = settings_service.get_map(db)
    try:
        grabbed = await process_publication(
            db,
            publication,
            cfg,
            recent_days=settings_service.as_int(cfg, "auto_search_recent_days", 30),
            max_grabs=settings_service.as_int(cfg, "auto_search_max_grabs", 3),
        )
    except ProwlarrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return grabbed
