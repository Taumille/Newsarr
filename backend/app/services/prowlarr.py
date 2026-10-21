"""Prowlarr API client.

Newsarr does not implement indexer protocols (Newznab/Torznab) itself -- it
delegates all searching to a Prowlarr instance, exactly the way Radarr/Sonarr
delegate to an indexer. We talk to Prowlarr's aggregate search endpoint which
fans a query out across every indexer the user has configured there.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ..models import DownloadProtocol
from ..schemas import Release, ReleaseCategory

logger = logging.getLogger(__name__)


class ProwlarrError(RuntimeError):
    pass


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Prowlarr returns ISO-8601, usually with a trailing Z.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ProwlarrClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        if not base_url:
            raise ProwlarrError("Prowlarr URL is not configured")
        if not api_key:
            raise ProwlarrError("Prowlarr API key is not configured")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -- helpers ----------------------------------------------------------- #
    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key, "Accept": "application/json"}

    @staticmethod
    def _iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # -- API --------------------------------------------------------------- #
    async def test(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/system/status", headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()

    async def indexers(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/indexer", headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()

    async def search(
        self,
        query: str,
        categories: list[int] | None = None,
        indexer_ids: list[int] | None = None,
        limit: int = 100,
    ) -> list[Release]:
        """Aggregate search across all Prowlarr indexers."""
        params: dict[str, str] = {"query": query, "type": "search", "limit": str(limit)}
        if categories:
            params["categories"] = ",".join(str(c) for c in categories)
        if indexer_ids:
            params["indexerIds"] = ",".join(str(i) for i in indexer_ids)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/search", headers=self._headers(), params=params
            )
            if resp.status_code >= 400:
                raise ProwlarrError(
                    f"Prowlarr search failed ({resp.status_code}): {resp.text[:300]}"
                )
            payload = resp.json()

        releases: list[Release] = []
        for item in payload:
            releases.append(self._to_release(item))

        # Newest first -- most useful for periodicals.
        releases.sort(key=lambda r: (r.publish_date or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        return releases

    @staticmethod
    def _to_release(item: dict) -> Release:
        magnet = item.get("magnetUrl") or ""
        download = item.get("downloadUrl") or ""
        protocol = DownloadProtocol.usenet if item.get("protocol") == "usenet" else DownloadProtocol.torrent
        cats = [
            ReleaseCategory(id=c.get("id"), name=c.get("name", ""))
            for c in (item.get("categories") or [])
        ]
        return Release(
            guid=str(item.get("guid") or ""),
            title=item.get("title") or "",
            indexer=item.get("indexer") or "",
            indexer_id=item.get("indexerId"),
            size=int(item.get("size") or 0),
            download_url=download,
            magnet_url=magnet,
            info_url=item.get("infoUrl") or "",
            publish_date=_parse_date(item.get("publishDate")),
            protocol=protocol,
            categories=cats,
            seeders=item.get("seeders"),
        )
