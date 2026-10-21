"""Build integration clients from stored settings."""

from __future__ import annotations

from .prowlarr import ProwlarrClient
from .qbittorrent import QBittorrentClient


def prowlarr_from_settings(cfg: dict[str, str]) -> ProwlarrClient:
    return ProwlarrClient(cfg.get("prowlarr_url", ""), cfg.get("prowlarr_api_key", ""))


def qbittorrent_from_settings(cfg: dict[str, str]) -> QBittorrentClient:
    return QBittorrentClient(
        cfg.get("qbittorrent_url", ""),
        cfg.get("qbittorrent_username", ""),
        cfg.get("qbittorrent_password", ""),
    )
