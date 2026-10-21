"""Settings + connection tests."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import SettingsModel, SettingsUpdate, TestResult
from ..services import settings as settings_service
from ..services.clients import prowlarr_from_settings, qbittorrent_from_settings
from ..services.prowlarr import ProwlarrError
from ..services.qbittorrent import QBittorrentError

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=SettingsModel)
def get_settings(db: Session = Depends(get_db)):
    return settings_service.get_all(db)


@router.put("", response_model=SettingsModel)
def put_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    return settings_service.update(db, payload)


@router.post("/test/prowlarr", response_model=TestResult)
async def test_prowlarr(payload: SettingsUpdate, db: Session = Depends(get_db)):
    # Allow testing credentials typed in the form before they are saved.
    cfg = settings_service.get_map(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            cfg[key] = str(value)
    try:
        client = prowlarr_from_settings(cfg)
        status = await client.test()
        return TestResult(
            ok=True,
            message=f"Connected to Prowlarr {status.get('version', '')}".strip(),
            details={"version": status.get("version", "")},
        )
    except (ProwlarrError, Exception) as exc:  # noqa: BLE001
        return TestResult(ok=False, message=str(exc))


@router.post("/test/qbittorrent", response_model=TestResult)
async def test_qbittorrent(payload: SettingsUpdate, db: Session = Depends(get_db)):
    cfg = settings_service.get_map(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            cfg[key] = str(value)
    try:
        client = qbittorrent_from_settings(cfg)
        info = await client.test()
        return TestResult(
            ok=True,
            message=f"Connected to qBittorrent {info.get('version', '')}".strip(),
            details=info,
        )
    except (QBittorrentError, Exception) as exc:  # noqa: BLE001
        return TestResult(ok=False, message=str(exc))


@router.get("/prowlarr/indexers", response_model=TestResult)
async def prowlarr_indexers(db: Session = Depends(get_db)):
    cfg = settings_service.get_map(db)
    try:
        client = prowlarr_from_settings(cfg)
        indexers = await client.indexers()
        return TestResult(
            ok=True,
            message=f"{len(indexers)} indexer(s) configured in Prowlarr",
            details={
                "indexers": [
                    {"id": i.get("id"), "name": i.get("name"), "enable": i.get("enable")}
                    for i in indexers
                ]
            },
        )
    except (ProwlarrError, Exception) as exc:  # noqa: BLE001
        return TestResult(ok=False, message=str(exc))
