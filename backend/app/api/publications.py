"""Publication CRUD + per-publication search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Publication, utcnow
from ..schemas import (
    Publication as PublicationSchema,
    PublicationCreate,
    PublicationUpdate,
    SearchResponse,
)
from ..services import settings as settings_service
from ..services.clients import prowlarr_from_settings
from ..services.naming import slugify
from ..services.prowlarr import ProwlarrError
from ..services.search import build_query, parse_categories

router = APIRouter(prefix="/api/v1/publications", tags=["publications"])


@router.get("", response_model=list[PublicationSchema])
def list_publications(
    monitored: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    stmt = select(Publication).order_by(Publication.title)
    if monitored is not None:
        stmt = stmt.where(Publication.monitored == monitored)
    return db.execute(stmt).scalars().all()


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
    return publication


def _get_or_404(db: Session, publication_id: int) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return publication


@router.get("/{publication_id}", response_model=PublicationSchema)
def get_publication(publication_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, publication_id)


@router.put("/{publication_id}", response_model=PublicationSchema)
def update_publication(
    publication_id: int, payload: PublicationUpdate, db: Session = Depends(get_db)
):
    publication = _get_or_404(db, publication_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(publication, key, value)
    if payload.title:
        publication.slug = slugify(payload.title)
    db.commit()
    db.refresh(publication)
    return publication


@router.delete("/{publication_id}", status_code=204)
def delete_publication(publication_id: int, db: Session = Depends(get_db)):
    publication = _get_or_404(db, publication_id)
    db.delete(publication)
    db.commit()


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
