"""Typed access to the key/value ``settings`` table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings as bootstrap
from ..models import AppSetting
from ..schemas import SettingsModel, SettingsUpdate

DEFAULTS = SettingsModel()

# Keys whose values are secrets and are never returned to the UI verbatim.
SECRET_KEYS = {"prowlarr_api_key", "qbittorrent_password"}


def get_all(db: Session) -> SettingsModel:
    rows = db.execute(select(AppSetting)).scalars().all()
    stored = {row.key: row.value for row in rows}
    data = DEFAULTS.model_dump()
    for key in data:
        if key in stored:
            data[key] = stored[key]
    model = SettingsModel(**data)
    model.prowlarr_api_key_set = bool(stored.get("prowlarr_api_key"))
    model.qbittorrent_password_set = bool(stored.get("qbittorrent_password"))
    # Never leak secrets back to the client; the *_set flags tell the UI they exist.
    for key in SECRET_KEYS:
        setattr(model, key, "")
    return model


def get_map(db: Session) -> dict[str, object]:
    """Return the raw stored settings (including secrets) for internal use."""
    rows = db.execute(select(AppSetting)).scalars().all()
    stored = {row.key: row.value for row in rows}
    data = DEFAULTS.model_dump()
    for key in data:
        if key in stored:
            data[key] = stored[key]
    return data


def as_bool(cfg: dict[str, object], key: str, default: bool = False) -> bool:
    value = cfg.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def as_int(cfg: dict[str, object], key: str, default: int) -> int:
    value = cfg.get(key, default)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def update(db: Session, patch: SettingsUpdate) -> SettingsModel:
    for key, value in patch.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        # A blank secret means "leave the stored value untouched".
        if key in SECRET_KEYS and value == "":
            continue
        _set(db, key, str(value))
    db.commit()
    return get_all(db)


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def library_root(db: Session) -> str:
    configured = get_map(db).get("library_root", "")
    return configured or str(bootstrap.media_root)
