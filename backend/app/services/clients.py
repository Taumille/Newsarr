"""Build integration clients from stored settings."""

from __future__ import annotations

from .prowlarr import ProwlarrClient
from .qbittorrent import QBittorrentClient


def prowlarr_from_settings(cfg: dict[str, object]) -> ProwlarrClient:
    return ProwlarrClient(str(cfg.get("prowlarr_url", "")), str(cfg.get("prowlarr_api_key", "")))


def qbittorrent_from_settings(cfg: dict[str, object]) -> QBittorrentClient:
    return QBittorrentClient(
        str(cfg.get("qbittorrent_url", "")),
        str(cfg.get("qbittorrent_username", "")),
        str(cfg.get("qbittorrent_password", "")),
    )
