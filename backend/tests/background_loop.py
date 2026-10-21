"""Verify the background queue loop updates progress on its own.

Grabs a release and then watches the Queue *without* calling /queue/sync,
relying solely on the background task (poll interval forced to 1s).

Run with: .venv/bin/python tests/background_loop.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="newsarr-loop-"))
os.environ["NEWSARR_DATA_DIR"] = str(TMP / "data")
os.environ["NEWSARR_QUEUE_POLL_SECONDS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.torrent import _bencode, torrent_info_hash  # noqa: E402

RELEASE_TITLE = "The Guardian 2026-10-21 PDF"
DOWNLOAD_DIR = TMP / "downloads"
DOWNLOAD_DIR.mkdir(parents=True)
COMPLETED_FILE = DOWNLOAD_DIR / "issue.pdf"
COMPLETED_FILE.write_bytes(b"%PDF-1.4 issue\n")

TORRENT_BYTES = _bencode(
    {b"info": {b"length": 10, b"name": b"Guardian", b"piece length": 1, b"pieces": b"a" * 20}}
)
EXPECTED_HASH = torrent_info_hash(TORRENT_BYTES)
DOWNLOAD_URL = ""


class MockProwlarr(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/v1/search"):
            self._json(
                [
                    {
                        "guid": "g1",
                        "title": RELEASE_TITLE,
                        "indexerId": 1,
                        "indexer": "Mock",
                        "size": 10,
                        "downloadUrl": DOWNLOAD_URL,
                        "publishDate": "2026-10-21T06:00:00Z",
                        "protocol": "torrent",
                        "categories": [{"id": 7010, "name": "Books/Mags"}],
                    }
                ]
            )
        elif self.path.startswith("/download"):
            body = TORRENT_BYTES
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class MockQbittorrent(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, text="", status=200, ct="text/plain"):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path.startswith("/api/v2/auth/login"):
            self._send("Ok.")
        else:
            self._send("Ok.")

    def do_GET(self):
        if self.path.startswith("/api/v2/app/version"):
            self._send("5.0.0")
        elif self.path.startswith("/api/v2/torrents/info"):
            self._send(
                json.dumps(
                    [
                        {
                            "hash": EXPECTED_HASH,
                            "name": "Guardian",
                            "progress": 1.0,
                            "state": "uploading",
                            "save_path": str(DOWNLOAD_DIR),
                            "content_path": str(COMPLETED_FILE),
                        }
                    ]
                ),
                ct="application/json",
            )
        else:
            self._send("", 404)


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def main() -> None:
    prowlarr_server, prowlarr_url = serve(MockProwlarr)
    qbit_server, qbit_url = serve(MockQbittorrent)

    global DOWNLOAD_URL
    DOWNLOAD_URL = f"{prowlarr_url}/download"

    library_root = TMP / "library"

    with TestClient(app) as client:
        client.put(
            "/api/v1/settings",
            json={
                "prowlarr_url": prowlarr_url,
                "prowlarr_api_key": "k",
                "qbittorrent_url": qbit_url,
                "qbittorrent_username": "admin",
                "qbittorrent_password": "pw",
                "library_root": str(library_root),
            },
        )
        pub = client.post(
            "/api/v1/publications", json={"title": "The Guardian"}
        ).json()
        release = client.post(f"/api/v1/publications/{pub['id']}/search").json()["releases"][0]
        record = client.post(
            "/api/v1/queue", json={"publication_id": pub["id"], "release": release}
        ).json()
        print(f"Grabbed record {record['id']}; waiting for the background loop...")

        status = record["status"]
        deadline = time.time() + 20
        while time.time() < deadline:
            recs = client.get("/api/v1/queue").json()["records"]
            current = next(x for x in recs if x["id"] == record["id"])
            status = current["status"]
            if status == "imported":
                break
            time.sleep(0.5)

    prowlarr_server.shutdown()
    qbit_server.shutdown()

    ok = status == "imported"
    print(f"  [{'PASS' if ok else 'FAIL'}] background loop reached status={status!r}")
    if not ok:
        raise SystemExit(1)
    print("Background-loop check passed ✅")


if __name__ == "__main__":
    main()
