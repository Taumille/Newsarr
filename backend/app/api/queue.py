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
from ..services.qbittorrent import QBittorrentError, normalize_name
from ..services.sync import resolve_record_hash, sync_queue
from ..services.torrent import magnet_info_hash

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


@router.get("/diagnostics")
async def diagnostics(db: Session = Depends(get_db)):
    """Show exactly what Newsarr stored vs. what the download client has.

    Declared before ``/{record_id}`` so the literal path wins the route match.
    """
    cfg = settings_service.get_map(db)
    torrents: list[dict] = []
    client_info: dict = {}
    try:
        client = qbittorrent_from_settings(cfg)
        torrents = await client.torrents()
        client_info = {"reachable": True, "torrent_count": len(torrents)}
    except QBittorrentError as exc:
        client_info = {"reachable": False, "error": str(exc)}

    by_hash = {(t.get("hash") or "").lower(): t for t in torrents}
    by_name = {normalize_name(t.get("name", "")): t for t in torrents}

    records = (
        db.execute(select(DownloadRecord).order_by(DownloadRecord.added_at.desc()))
        .scalars()
        .all()
    )

    record_rows = []
    for record in records:
        stored = (record.client_hash or "").lower()
        magnet_hash = magnet_info_hash(record.magnet_url)
        matched_by = None
        if stored and stored in by_hash:
            matched_by = "hash"
        elif magnet_hash and magnet_hash in by_hash:
            matched_by = "magnet"
        elif by_name.get(normalize_name(record.title)):
            matched_by = "name"
        record_rows.append(
            {
                "id": record.id,
                "title": record.title,
                "status": record.status.value,
                "progress": record.progress,
                "stored_client_hash": record.client_hash,
                "magnet_hash": magnet_hash,
                "has_magnet": bool(record.magnet_url),
                "has_download_url": bool(record.download_url),
                "protocol": record.protocol.value,
                "matched_by": matched_by,
            }
        )

    return {
        "client": client_info,
        "torrents": [
            {
                "hash": t.get("hash"),
                "name": t.get("name"),
                "progress": t.get("progress"),
                "state": t.get("state"),
                "category": t.get("category"),
                "save_path": t.get("save_path"),
                "content_path": t.get("content_path"),
            }
            for t in torrents
        ],
        "records": record_rows,
    }


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
    # Recover the info hash from the release before re-checking, so a record with
    # a missing/wrong hash gets a second chance to match.
    resolved = await resolve_record_hash(record)
    if resolved:
        record.client_hash = resolved
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
