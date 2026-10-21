"""System status."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..database import get_db
from ..models import DownloadRecord, Publication, TrackedStatus
from ..schemas import SystemStatus
from ..services import settings as settings_service

router = APIRouter(prefix="/api/v1/system", tags=["system"])

ACTIVE = (TrackedStatus.queued, TrackedStatus.downloading, TrackedStatus.completed)


@router.get("/status", response_model=SystemStatus)
def status(db: Session = Depends(get_db)):
    cfg = settings_service.get_map(db)
    publication_count = db.execute(select(func.count(Publication.id))).scalar_one()
    active = db.execute(
        select(func.count(DownloadRecord.id)).where(DownloadRecord.status.in_(ACTIVE))
    ).scalar_one()
    return SystemStatus(
        version=__version__,
        publication_count=publication_count,
        active_downloads=active,
        prowlarr_configured=bool(cfg.get("prowlarr_url") and cfg.get("prowlarr_api_key")),
        download_client_configured=bool(cfg.get("qbittorrent_url")),
        library_root=settings_service.library_root(db),
    )
