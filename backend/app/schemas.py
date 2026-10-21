"""Pydantic request/response schemas (the public API surface)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import DownloadProtocol, TrackedStatus


# --------------------------------------------------------------------------- #
# Publications
# --------------------------------------------------------------------------- #
class PublicationBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    monitored: bool = True
    keywords: str = ""
    categories: str = "7010,7020,7030"
    language: str = ""
    country: str = ""
    preferred_format: str = "any"
    folder: str = ""
    cover_url: str = ""


class PublicationCreate(PublicationBase):
    pass


class PublicationUpdate(BaseModel):
    title: str | None = None
    monitored: bool | None = None
    keywords: str | None = None
    categories: str | None = None
    language: str | None = None
    country: str | None = None
    preferred_format: str | None = None
    folder: str | None = None
    cover_url: str | None = None


class Publication(PublicationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    created_at: datetime
    updated_at: datetime
    last_search_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Releases (Prowlarr search results)
# --------------------------------------------------------------------------- #
class ReleaseCategory(BaseModel):
    id: int | None = None
    name: str = ""


class Release(BaseModel):
    """A single search result, shaped like Prowlarr's search response."""

    guid: str = ""
    title: str = ""
    indexer: str = ""
    indexer_id: int | None = None
    size: int = 0
    download_url: str = ""
    magnet_url: str = ""
    info_url: str = ""
    publish_date: datetime | None = None
    protocol: DownloadProtocol = DownloadProtocol.torrent
    categories: list[ReleaseCategory] = Field(default_factory=list)
    seeders: int | None = None


class SearchResponse(BaseModel):
    query: str
    releases: list[Release]


# --------------------------------------------------------------------------- #
# Grab / queue
# --------------------------------------------------------------------------- #
class GrabRequest(BaseModel):
    publication_id: int | None = None
    release: Release


class DownloadRecordSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    publication_id: int | None
    title: str
    guid: str
    indexer: str
    indexer_id: int | None
    protocol: DownloadProtocol
    size: int
    client: str
    client_hash: str
    save_path: str
    content_path: str
    status: TrackedStatus
    progress: int
    error_message: str
    imported_path: str
    added_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class QueueResponse(BaseModel):
    records: list[DownloadRecordSchema]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
class SettingsModel(BaseModel):
    prowlarr_url: str = ""
    prowlarr_api_key: str = ""
    qbittorrent_url: str = ""
    qbittorrent_username: str = ""
    qbittorrent_password: str = ""
    qbittorrent_category: str = "newsarr"
    qbittorrent_save_path: str = ""
    library_root: str = ""
    naming_template: str = "{title} - {date}"
    # Strip secrets when returning settings to the UI.
    prowlarr_api_key_set: bool = False
    qbittorrent_password_set: bool = False


class SettingsUpdate(BaseModel):
    prowlarr_url: str | None = None
    prowlarr_api_key: str | None = None
    qbittorrent_url: str | None = None
    qbittorrent_username: str | None = None
    qbittorrent_password: str | None = None
    qbittorrent_category: str | None = None
    qbittorrent_save_path: str | None = None
    library_root: str | None = None
    naming_template: str | None = None


# --------------------------------------------------------------------------- #
# System / test
# --------------------------------------------------------------------------- #
class TestResult(BaseModel):
    ok: bool
    message: str
    details: dict | None = None


class SystemStatus(BaseModel):
    version: str
    publication_count: int
    active_downloads: int
    prowlarr_configured: bool
    download_client_configured: bool
    library_root: str
