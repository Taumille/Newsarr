"""Application-level configuration.

Only *bootstrap* settings live here (where the DB and data folders are, what
host/port to bind). User-facing configuration such as the Prowlarr URL/API key
and the qBittorrent credentials are stored in the database and edited from the
web UI -- never committed to the repo.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    # Keep everything the app writes under a single, predictable folder.
    env = os.environ.get("NEWSARR_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".config" / "newsarr"


class BootstrapSettings(BaseSettings):
    """Settings that must be known before the database is opened."""

    model_config = SettingsConfigDict(env_prefix="NEWSARR_", extra="ignore")

    data_dir: Path = _default_data_dir()

    # Where the built React frontend lives (served by the API in production).
    frontend_dir: Path = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    host: str = "0.0.0.0"
    port: int = 7878

    # Background download-sync interval, in seconds.
    queue_poll_seconds: int = 20

    @property
    def database_path(self) -> Path:
        return self.data_dir / "newsarr.db"

    @property
    def media_root(self) -> Path:
        """Default library root when the user has not configured one."""
        return self.data_dir / "library"


settings = BootstrapSettings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
