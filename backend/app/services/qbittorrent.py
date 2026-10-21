"""qBittorrent Web API (v2) client."""

from __future__ import annotations

import logging
import re

import httpx

from ..schemas import Release
from .torrent import magnet_info_hash, torrent_info_hash

logger = logging.getLogger(__name__)


class QBittorrentError(RuntimeError):
    pass


def normalize_name(name: str) -> str:
    """Loose comparison key for matching a release to a qBittorrent torrent."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


async def fetch_torrent_hash(url: str, timeout: float = 30.0) -> str:
    """Download a .torrent URL and compute its info hash ('' on failure)."""
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return ""
            return torrent_info_hash(resp.content)
    except httpx.HTTPError:
        return ""


class QBittorrentClient:
    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
    ):
        if not base_url:
            raise QBittorrentError("qBittorrent URL is not configured")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    async def _login(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            f"{self.base_url}/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )

        if resp.status_code == 403:
            raise QBittorrentError(
                "qBittorrent answered the login with 403. Your IP is most likely "
                "temporarily banned after too many failed attempts -- wait a few "
                "minutes, then double-check the username and password."
            )
        if resp.status_code == 401:
            raise QBittorrentError(
                "qBittorrent answered the login with 401. This is usually its "
                "CSRF / Host-header protection: make sure the URL's host matches the "
                "one you use to reach qBittorrent, or turn off 'Host header "
                "validation' and CSRF protection in qBittorrent's WebUI settings."
            )
        if resp.status_code >= 400:
            raise QBittorrentError(
                f"qBittorrent login failed ({resp.status_code}): {resp.text[:200]}"
            )

        # Successful login is "Ok." (<= 5.1) or an empty 204 body (5.2+).
        body = resp.text.strip()
        if body and body.lower() != "ok.":
            raise QBittorrentError("Incorrect qBittorrent username or password.")

    def _client(self) -> httpx.AsyncClient:
        # When CSRF protection is enabled (the default), qBittorrent checks the
        # Origin/Referer header against the request's Host. Sending a matching
        # Referer keeps non-browser API clients working -- this is exactly what
        # Sonarr/Radarr do too.
        headers = {
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url,
        }
        return httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers)

    # -- API --------------------------------------------------------------- #
    async def test(self) -> dict:
        async with self._client() as client:
            # Every endpoint except /auth/login requires authentication, so we
            # must log in *first* -- probing an unauthenticated endpoint would
            # only ever return qBittorrent's 403.
            await self._login(client)
            version = await client.get(f"{self.base_url}/api/v2/app/version")
            if version.status_code >= 400:
                raise QBittorrentError(
                    f"Logged in, but reading the version failed ({version.status_code}). "
                    "Check that the URL points at qBittorrent's WebUI."
                )
            return {"version": version.text.strip()}

    async def add(
        self,
        release: Release,
        save_path: str = "",
        category: str = "",
        torrent_bytes: bytes | None = None,
    ) -> str:
        """Add a release and return its info hash (best effort)."""
        async with self._client() as client:
            await self._login(client)

            data: dict[str, str] = {}
            if save_path:
                data["savepath"] = save_path
            if category:
                data["category"] = category

            info_hash = ""
            magnet_url = release.magnet_url.strip()
            if magnet_url:
                # A magnet carries the info hash; trust it.
                info_hash = magnet_info_hash(magnet_url)
                data["urls"] = magnet_url
                resp = await client.post(f"{self.base_url}/api/v2/torrents/add", data=data)
            else:
                blob = torrent_bytes
                if blob is None:
                    blob = await self._download_torrent(release)
                # Compute the info hash from the torrent metadata itself instead
                # of guessing by name -- name matching is unreliable and was the
                # reason a grabbed download could sit in the queue at 0%.
                info_hash = torrent_info_hash(blob)
                files = {"torrents": ("release.torrent", blob, "application/x-bittorrent")}
                resp = await client.post(
                    f"{self.base_url}/api/v2/torrents/add", data=data, files=files
                )

            if resp.status_code >= 400:
                raise QBittorrentError(f"qBittorrent rejected the torrent: {resp.text[:300]}")

            # qBittorrent returns 200 with "Fails." when it couldn't add.
            if resp.text.strip().lower().startswith("fail"):
                raise QBittorrentError(
                    "qBittorrent reported 'Fails.' -- the release may already exist or be unreachable."
                )

            if info_hash:
                return info_hash
            # Last resort (e.g. a magnet with no btih): fall back to name matching.
            return await self._resolve_hash(client, release, category)

    async def _download_torrent(self, release: Release) -> bytes:
        if not release.download_url:
            raise QBittorrentError("Release has neither a magnet nor a download URL")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(release.download_url)
            resp.raise_for_status()
            return resp.content

    async def _resolve_hash(
        self, client: httpx.AsyncClient, release: Release, category: str
    ) -> str:
        match = magnet_info_hash(release.magnet_url)
        if match:
            return match

        params = {}
        if category:
            params["category"] = category
        info = await client.get(f"{self.base_url}/api/v2/torrents/info", params=params)
        if info.status_code >= 400:
            return ""
        target = normalize_name(release.title)
        if not target:
            return ""
        for torrent in info.json():
            name = normalize_name(torrent.get("name", ""))
            if name and (target in name or name in target):
                return (torrent.get("hash") or "").lower()
        # Never guess: an unmatched name means we don't know the hash.
        return ""

    async def torrents(self, hashes: list[str] | None = None) -> list[dict]:
        async with self._client() as client:
            await self._login(client)
            params = {"hashes": "|".join(hashes)} if hashes else {}
            resp = await client.get(f"{self.base_url}/api/v2/torrents/info", params=params)
            resp.raise_for_status()
            return resp.json()

    async def delete(self, info_hash: str, delete_files: bool = False) -> None:
        async with self._client() as client:
            await self._login(client)
            await client.post(
                f"{self.base_url}/api/v2/torrents/delete",
                data={"hashes": info_hash, "deleteFiles": "true" if delete_files else "false"},
            )
