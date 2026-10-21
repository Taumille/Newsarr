"""Download queue / history management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DownloadRecord, TrackedStatus
from ..schemas import DownloadRecordSchema, GrabRequest, QueueResponse
from ..services import settings as settings_service
from ..services.clients import qbittorrent_from_settings
from ..services.grab import GrabError, grab_release
from ..services.qbittorrent import QBittorrentError
from ..services.sync import sync_queue

router = APIRouter(prefix="/api/v1/queue", tags=["queue"])

ACTIVE = (TrackedStatus.queued, TrackedStatus.downloading, TrackedStatus.completed)


@router.get("", response_model=QueueResponse)
def list_queue(
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    stmt = select(DownloadRecord).order_by(DownloadRecord.added_at.desc())
    if active_only:
        stmt = stmt.where(DownloadRecord.status.in_(ACTIVE))
    return QueueResponse(records=db.execute(stmt).scalars().all())


@router.post("", response_model=DownloadRecordSchema, status_code=201)
async def grab(payload: GrabRequest, db: Session = Depends(get_db)):
    try:
        record = await grab_release(db, payload.release, payload.publication_id)
    except GrabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return record


def _get_or_404(db: Session, record_id: int) -> DownloadRecord:
    record = db.get(DownloadRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Download not found")
    return record


@router.get("/{record_id}", response_model=DownloadRecordSchema)
def get_download(record_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, record_id)


@router.delete("/{record_id}", status_code=204)
async def delete_download(
    record_id: int,
    delete_files: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    record = _get_or_404(db, record_id)
    if record.client_hash:
        try:
            cfg = settings_service.get_map(db)
            client = qbittorrent_from_settings(cfg)
            await client.delete(record.client_hash, delete_files=delete_files)
        except QBittorrentError:
            pass  # Already gone from the client; still remove our record.
    db.delete(record)
    db.commit()


@router.post("/{record_id}/retry", response_model=DownloadRecordSchema)
async def retry_download(record_id: int, db: Session = Depends(get_db)):
    record = _get_or_404(db, record_id)
    record.status = TrackedStatus.queued
    record.progress = 0
    record.error_message = ""
    db.commit()
    db.refresh(record)
    await sync_queue(db)
    return record


@router.post("/sync", response_model=QueueResponse)
async def force_sync(db: Session = Depends(get_db)):
    await sync_queue(db)
    records = (
        db.execute(select(DownloadRecord).order_by(DownloadRecord.added_at.desc()))
        .scalars()
        .all()
    )
    return QueueResponse(records=records)
