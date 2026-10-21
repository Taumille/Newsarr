"""End-to-end smoke test.

Spins up mock Prowlarr and qBittorrent HTTP servers, points a Newsarr instance
at them, then exercises: search -> grab -> sync -> import.

Run with:  .venv/bin/python tests/e2e_smoke.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Point the app at a throwaway data dir before importing it.
TMP = Path(tempfile.mkdtemp(prefix="newsarr-e2e-"))
os.environ["NEWSARR_DATA_DIR"] = str(TMP / "data")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.torrent import _bencode, torrent_info_hash  # noqa: E402

# A valid, minimal .torrent so the client can compute a real info hash.
TORRENT_BYTES = _bencode(
    {
        b"announce": b"http://tracker.test/announce",
        b"info": {
            b"length": 1234,
            b"name": b"The Guardian 2026-10-21",
            b"piece length": 16384,
            b"pieces": b"a" * 20,
        },
    }
)
EXPECTED_HASH = torrent_info_hash(TORRENT_BYTES)

# --------------------------------------------------------------------------- #
# Mock download file (what qBittorrent would have produced)
# --------------------------------------------------------------------------- #
DOWNLOAD_DIR = TMP / "downloads"
DOWNLOAD_DIR.mkdir(parents=True)
COMPLETED_FILE = DOWNLOAD_DIR / "The.Guardian.2026-10-21.pdf"
COMPLETED_FILE.write_bytes(b"%PDF-1.4 fake newspaper\n")

RELEASE_TITLE = "The Guardian 2026-10-21 PDF"

STATE: dict[str, object] = {"added": False}
# Filled in once the mock server is listening.
DOWNLOAD_URL = ""


class MockProwlarr(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/v1/system/status"):
            self._json({"version": "1.30.0"})
        elif self.path.startswith("/api/v1/indexer"):
            self._json([{"id": 1, "name": "MockIndexer", "enable": True}])
        elif self.path.startswith("/api/v1/search"):
            self._json(
                [
                    {
                        "guid": "mock-guid-1",
                        "title": RELEASE_TITLE,
                        "indexerId": 1,
                        "indexer": "MockIndexer",
                        "size": 2048,
                        "downloadUrl": DOWNLOAD_URL,
                        "magnetUrl": "",
                        "infoUrl": DOWNLOAD_URL,
                        "publishDate": "2026-10-21T06:00:00Z",
                        "protocol": "torrent",
                        "categories": [{"id": 7010, "name": "Books/Mags"}],
                        "seeders": 12,
                    }
                ]
            )
        elif self.path.startswith("/download"):
            body = TORRENT_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/x-bittorrent")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class MockQbittorrent(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, text="", status=200, content_type="text/plain"):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path.startswith("/api/v2/auth/login"):
            self._send("Ok.")
        elif self.path.startswith("/api/v2/torrents/add"):
            STATE["added"] = True
            self._send("Ok.")
        else:
            self._send("", 404)

    def do_GET(self):
        if self.path.startswith("/api/v2/app/version"):
            self._send("4.6.2")
        elif self.path.startswith("/api/v2/torrents/info"):
            self._send(
                json.dumps(
                    [
                        {
                            "hash": EXPECTED_HASH,
                            "name": RELEASE_TITLE,
                            "progress": 1.0,
                            "state": "uploading",
                            "save_path": str(DOWNLOAD_DIR),
                            "content_path": str(COMPLETED_FILE),
                        }
                    ]
                ),
                content_type="application/json",
            )
        else:
            self._send("", 404)


def serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def main() -> None:
    prowlarr_server, prowlarr_url = serve(MockProwlarr)
    qbit_server, qbit_url = serve(MockQbittorrent)

    global DOWNLOAD_URL
    DOWNLOAD_URL = f"{prowlarr_url}/download"

    failures: list[str] = []

    def check(label: str, condition: bool, extra: object = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label} {extra if not condition else ''}")
        if not condition:
            failures.append(label)

    library_root = TMP / "library"

    with TestClient(app) as client:
        print("Configuring settings from mock servers...")
        r = client.put(
            "/api/v1/settings",
            json={
                "prowlarr_url": prowlarr_url,
                "prowlarr_api_key": "test-key",
                "qbittorrent_url": qbit_url,
                "qbittorrent_username": "admin",
                "qbittorrent_password": "adminadmin",
                "qbittorrent_category": "newsarr",
                "library_root": str(library_root),
            },
        )
        check("settings saved", r.status_code == 200)

        print("Testing connections...")
        check("prowlarr test", client.post("/api/v1/settings/test/prowlarr", json={}).json()["ok"])
        check("qbit test", client.post("/api/v1/settings/test/qbittorrent", json={}).json()["ok"])

        print("Creating publication...")
        r = client.post(
            "/api/v1/publications",
            json={"title": "The Guardian", "keywords": "pdf", "categories": "7010"},
        )
        check("publication created", r.status_code == 201, r.text)
        pub_id = r.json()["id"]

        print("Searching via publication...")
        r = client.post(f"/api/v1/publications/{pub_id}/search")
        check("search ok", r.status_code == 200, r.text)
        releases = r.json()["releases"]
        check("one release returned", len(releases) == 1, releases)
        release = releases[0]

        print("Grabbing release...")
        r = client.post(
            "/api/v1/queue", json={"publication_id": pub_id, "release": release}
        )
        check("grab ok", r.status_code == 201, r.text)
        record_id = r.json()["id"]
        check("client add called", bool(STATE["added"]))
        check(
            "computed info hash stored",
            r.json()["client_hash"] == EXPECTED_HASH,
            r.json()["client_hash"],
        )

        print("Syncing queue (mock client reports complete)...")
        r = client.post("/api/v1/queue/sync")
        check("sync ok", r.status_code == 200, r.text)

        record = client.get(f"/api/v1/queue/{record_id}").json()
        check("record imported", record["status"] == "imported", record["status"])
        check("progress 100", record["progress"] == 100, record["progress"])

        imported = Path(record["imported_path"]) if record["imported_path"] else None
        check("imported path set", bool(imported))
        check("file exists", bool(imported and imported.exists()))
        if imported:
            check("named with date", "2026-10-21" in imported.name, imported.name)
            check("under library root", str(imported).startswith(str(library_root)))
            check("in title folder", imported.parent.name == "the-guardian", imported.parent.name)

        print("Checking system status...")
        status = client.get("/api/v1/system/status").json()
        check("prowlarr configured", status["prowlarr_configured"] is True)
        check("client configured", status["download_client_configured"] is True)

        print("Checking SPA is served...")
        r = client.get("/")
        check("index.html served", r.status_code == 200 and "root" in r.text)

    prowlarr_server.shutdown()
    qbit_server.shutdown()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        raise SystemExit(1)
    print("All checks passed ✅")


if __name__ == "__main__":
    main()
